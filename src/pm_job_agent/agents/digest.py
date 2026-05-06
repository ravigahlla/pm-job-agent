"""Build a short, high-signal summary string for the email digest."""

from __future__ import annotations

import json
import re

from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.models.llm import LLMClient
from pm_job_agent.services.types import RankedJobDict

_MAX_HIGHLIGHTS = 3
_JSON_EXTRACT_RE = re.compile(r"\{[\s\S]*\}", flags=re.MULTILINE)


def _tier_counts(
    new_jobs: list[RankedJobDict],
    *,
    high_score_min: float,
    next_score_min: float,
) -> tuple[int, int]:
    high = sum(1 for j in new_jobs if float(j.get("score", 0.0)) >= high_score_min)
    next_tier = sum(
        1
        for j in new_jobs
        if next_score_min <= float(j.get("score", 0.0)) < high_score_min
    )
    return high, next_tier


def _high_signal_highlights(
    new_jobs: list[RankedJobDict],
    *,
    high_score_min: float,
    limit: int = _MAX_HIGHLIGHTS,
) -> list[dict]:
    # Preserve upstream ranking order; just filter + cap.
    out: list[dict] = []
    for j in new_jobs:
        if float(j.get("score", 0.0)) < high_score_min:
            continue
        out.append({"title": j.get("title", ""), "company": j.get("company", "")})
        if len(out) >= limit:
            break
    return out


def _build_llm_prompt(
    *,
    new_count: int,
    high_count: int,
    next_count: int,
    highlights: list[dict],
    high_score_min: float,
) -> str:
    return (
        "You are generating the single-sentence summary line for a PM job digest email.\n"
        "Return ONLY valid JSON with this exact schema:\n"
        '{\n'
        '  "summary": "<ONE sentence. Stats-first. No fluff.>",\n'
        '  "highlights": [{"title": "...", "company": "..."}]\n'
        "}\n\n"
        "Rules:\n"
        "- The summary MUST begin with: \"New: <new_count>\".\n"
        "- The summary MUST include counts for the high tier and next tier.\n"
        f"- High tier means score ≥ {high_score_min:.2f}.\n"
        "- If there are high-tier highlights, name up to 3 as \"<title> @ <company>\".\n"
        "- Do NOT mention candidate background. Do NOT use adjectives like \"excellent\".\n"
        "- Do NOT include any extra keys or any text outside the JSON.\n\n"
        "Data:\n"
        f"- new_count: {new_count}\n"
        f"- high_count: {high_count}\n"
        f"- next_count: {next_count}\n"
        f"- highlights: {json.dumps(highlights, ensure_ascii=False)}\n"
    )


def _parse_llm_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None

    # If the model wraps JSON, extract the first JSON object.
    match = _JSON_EXTRACT_RE.search(text)
    candidate = match.group(0) if match else text
    try:
        data = json.loads(candidate)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    if not isinstance(summary, str):
        return None
    return data


def digest_jobs(state: CoreLoopState, *, llm: LLMClient) -> dict:
    settings = get_settings()

    ranked = state.get("ranked_jobs") or []
    new_ids = set(state.get("new_job_ids") or [])
    new_jobs = [j for j in ranked if j.get("id") in new_ids]

    new_count = len(new_jobs)
    high_count, next_count = _tier_counts(
        new_jobs,
        high_score_min=settings.notify_high_score_min,
        next_score_min=settings.notify_next_score_min,
    )
    highlights = _high_signal_highlights(
        new_jobs, high_score_min=settings.notify_high_score_min, limit=_MAX_HIGHLIGHTS
    )

    # If there is nothing new, keep this extremely deterministic.
    if new_count == 0:
        return {"digest": "New: 0. No new roles in this run."}

    prompt = _build_llm_prompt(
        new_count=new_count,
        high_count=high_count,
        next_count=next_count,
        highlights=highlights,
        high_score_min=settings.notify_high_score_min,
    )
    raw = llm.generate(prompt, system_prompt="Return ONLY JSON.")
    parsed = _parse_llm_json(raw)
    if not parsed:
        # Safe deterministic fallback (no fluff).
        named = ", ".join(f"{h['title']} @ {h['company']}".strip() for h in highlights if h)
        highlight_part = f" Highlights: {named}." if named else ""
        return {
            "digest": (
                f"New: {new_count}. High-tier: {high_count}. Next-tier: {next_count}."
                + highlight_part
            )
        }

    summary = parsed.get("summary", "").strip()
    return {"digest": summary}


def make_digest_node(llm: LLMClient):
    def _node(state: CoreLoopState) -> dict:
        return digest_jobs(state, llm=llm)

    return _node
