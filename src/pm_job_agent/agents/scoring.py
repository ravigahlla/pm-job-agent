"""Score each discovered job against the user's background using LLM semantic scoring.

Scoring pipeline per job:
  1. Keyword pre-filter (free, instant):
     - Any exclude_keyword in title/description → score 0.0, no LLM call.
     - Zero include_keyword matches → score 0.0, no LLM call.
  2. LLM scoring (for jobs that pass pre-filter):
     - Sends job title, company, location, description snippet + agent-context.md excerpt
       to a cheap scoring model (SCORING_LLM_PROVIDER / SCORING_MODEL in .env).
     - LLM returns JSON: {"score": 0.0-1.0, "rationale": "1-2 sentences"}.
     - If JSON parsing fails, logs a warning and falls back to keyword score.

Location is now passed to the LLM as context rather than used as a hard filter.
This fixes the previous behaviour where ambiguous or blank locations zeroed out good fits.

The scoring node is a factory (make_score_node) so the LLM client and agent context
are injected at graph-build time, keeping the node function itself pure and testable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from pm_job_agent.config.search_profile import SearchProfile, load_search_profile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.models.llm import LLMClient
from pm_job_agent.services.types import JobDict, RankedJobDict

logger = logging.getLogger(__name__)

_INCLUDE_BOOST = 0.2
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0

# Cap context sent to the LLM to keep token usage predictable across runs.
_CONTEXT_MAX_CHARS = 2000

# Base system prompt — generic scoring instructions used when no criteria file is configured.
_SCORING_SYSTEM_BASE = (
    "You are evaluating job fit for a senior product manager candidate. "
    "Return ONLY valid JSON with two keys: "
    '{"score": <float 0.0-1.0>, "rationale": "<1-2 sentences>"}. '
    "Score guide: 0.8+ strong match, 0.5-0.79 worth considering, below 0.5 weak fit. "
    "Consider seniority, domain fit, required skills, and location preference holistically. "
    "Do not add any text outside the JSON object."
)


def _build_scoring_system(criteria: str = "") -> str:
    """Build the full system prompt, optionally appending personalized scoring criteria.

    Criteria are injected into the system prompt (not the user prompt) so that
    Anthropic prompt caching can apply across all per-job calls in a run —
    the system prompt is constant for the entire run, so the criteria content
    costs input tokens only once.
    """
    if not criteria.strip():
        return _SCORING_SYSTEM_BASE
    return (
        _SCORING_SYSTEM_BASE
        + "\n\nCandidate-specific scoring criteria (use these to calibrate your score):\n"
        + criteria.strip()
    )


def _build_scoring_prompt(job: JobDict, context_excerpt: str) -> str:
    location = job.get("location") or "not specified"
    return (
        f"Role: {job['title']} at {job['company']} ({location})\n"
        f"Description: {job.get('description_snippet', '(none)')}\n\n"
        f"Candidate background:\n{context_excerpt}"
    )


def _keyword_score(job: JobDict, profile: SearchProfile) -> float:
    """Keyword-only score used as fallback when LLM response is unparseable."""
    haystack = (job.get("title", "") + " " + job.get("description_snippet", "")).lower()
    score = _SCORE_MIN
    for kw in profile.include_keywords:
        if kw.lower() in haystack:
            score += _INCLUDE_BOOST
    return min(score, _SCORE_MAX)


def _passes_pre_filter(job: JobDict, profile: SearchProfile) -> tuple[bool, str]:
    """Return (passes, disqualification_reason).

    Checks exclude_keywords first (immediate disqualification), then requires at least
    one include_keyword match. Jobs that pass get an LLM score; those that don't get 0.0.
    Location is intentionally not checked here — the LLM handles it holistically.
    """
    haystack = (job.get("title", "") + " " + job.get("description_snippet", "")).lower()

    for kw in profile.exclude_keywords:
        if kw.lower() in haystack:
            return False, f"Excluded by keyword: '{kw}'"

    if profile.include_keywords:
        matched = [kw for kw in profile.include_keywords if kw.lower() in haystack]
        if not matched:
            return False, "No include keywords matched — skipped LLM scoring"

    return True, ""


def _parse_llm_response(raw: str) -> tuple[float, str] | None:
    """Extract (score, rationale) from the LLM's JSON response.

    Returns None if the response cannot be parsed so the caller can fall back gracefully.
    Handles responses where the model wraps the JSON in a markdown code fence.
    """
    # Strip optional markdown code fence the model may add despite instructions.
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Some models emit trailing commas or comments; try a lenient extraction.
        score_match = re.search(r'"score"\s*:\s*([0-9.]+)', cleaned)
        rationale_match = re.search(r'"rationale"\s*:\s*"([^"]*)"', cleaned)
        if score_match and rationale_match:
            return float(score_match.group(1)), rationale_match.group(1)
        return None

    score = data.get("score")
    rationale = data.get("rationale", "")
    if score is None or not isinstance(score, (int, float)):
        return None
    return float(max(_SCORE_MIN, min(_SCORE_MAX, score))), str(rationale)


def _llm_score_job(
    job: JobDict,
    profile: SearchProfile,
    llm: LLMClient,
    context_excerpt: str,
    scoring_system: str = _SCORING_SYSTEM_BASE,
) -> tuple[float, str]:
    """Call the LLM and return (score, rationale).

    Falls back to keyword score with an explanatory rationale if the LLM response
    cannot be parsed. This makes scoring degrade gracefully without crashing the run.
    """
    prompt = _build_scoring_prompt(job, context_excerpt)
    try:
        raw = llm.generate(prompt, system_prompt=scoring_system)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM call failed for job %s (%s): %s", job.get("id"), job.get("title"), exc)
        fallback = _keyword_score(job, profile)
        return fallback, f"LLM call failed ({exc}); keyword fallback score used."

    parsed = _parse_llm_response(raw)
    if parsed is None:
        logger.warning(
            "Could not parse LLM response for job %s (%s). Raw: %.120s",
            job.get("id"), job.get("title"), raw,
        )
        fallback = _keyword_score(job, profile)
        return fallback, "LLM response unparseable; keyword fallback score used."

    return parsed


def _score_single(
    job: JobDict,
    profile: SearchProfile,
    llm: LLMClient,
    context_excerpt: str,
    scoring_system: str = _SCORING_SYSTEM_BASE,
) -> RankedJobDict:
    passes, reason = _passes_pre_filter(job, profile)
    if not passes:
        return {**job, "score": _SCORE_MIN, "score_rationale": reason}

    score, rationale = _llm_score_job(job, profile, llm, context_excerpt, scoring_system=scoring_system)
    return {**job, "score": score, "score_rationale": rationale}


def make_score_node(llm: LLMClient) -> Callable[[CoreLoopState], dict]:
    """Return a LangGraph node function with the scoring LLM client bound.

    The search profile is loaded once at factory-call time (not on every job).
    Agent context is read from state at runtime — it is set by the load_context
    node which runs before score in the graph edge order.

    Pass a StubLLM or a mock in tests to control LLM output without API calls.
    """
    settings = get_settings()
    profile = load_search_profile(settings.search_profile_path)

    criteria_text = ""
    criteria_path = settings.scoring_criteria_path
    if criteria_path and criteria_path.exists():
        criteria_text = criteria_path.read_text(encoding="utf-8")
        logger.info(
            "Loaded scoring criteria from %s (%d chars).", criteria_path, len(criteria_text)
        )
    scoring_system = _build_scoring_system(criteria_text)

    def _score_jobs(state: CoreLoopState) -> dict:
        agent_context = state.get("agent_context") or ""
        context_excerpt = agent_context[:_CONTEXT_MAX_CHARS]
        jobs = state.get("jobs") or []
        ranked: list[RankedJobDict] = [
            _score_single(job, profile, llm, context_excerpt, scoring_system=scoring_system)
            for job in jobs
        ]
        ranked.sort(key=lambda j: j["score"], reverse=True)

        # Count LLM-scored jobs: those whose rationale doesn't contain fallback/pre-filter phrases.
        pre_filtered_phrases = ("fallback score used", "no include keywords", "excluded by keyword")
        llm_scored = sum(
            1 for j in ranked
            if not any(p in j.get("score_rationale", "").lower() for p in pre_filtered_phrases)
        )
        logger.info(
            "Scored %d jobs (%d via LLM, %d pre-filtered).",
            len(ranked), llm_scored, len(ranked) - llm_scored,
        )
        return {"ranked_jobs": ranked}

    return _score_jobs
