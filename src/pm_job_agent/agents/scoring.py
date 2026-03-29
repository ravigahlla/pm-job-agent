"""Score each discovered job against the user's SearchProfile.

Scoring logic (simple keyword pass):
  - Base score: 0.0
  - Score → 0.0 immediately if any exclude_keyword is found in title or description (disqualified)
  - Score → 0.0 if locations are configured, the job has a location, and it matches none of them
  - +0.2 for each include_keyword found in title or description_snippet (case-insensitive)
  - Final score is clamped to [0.0, 1.0]

Location matching is substring and case-insensitive: "San Francisco" matches "San Francisco, CA".
Jobs with a blank location field are never disqualified by location — blank means unknown, not wrong.

This is intentionally simple — good enough for Phase 1 ranking. A real fit score
(matching against agent_context, seniority signals, company stage) belongs in Phase 2.
"""

from __future__ import annotations

import logging

from pm_job_agent.config.search_profile import SearchProfile, load_search_profile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.services.types import JobDict, RankedJobDict

logger = logging.getLogger(__name__)

_INCLUDE_BOOST = 0.2
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0


def score_jobs(state: CoreLoopState) -> dict:
    """Attach a fit score to each job based on keyword matching from SearchProfile."""
    settings = get_settings()
    profile = load_search_profile(settings.search_profile_path)
    jobs = state.get("jobs") or []
    ranked = _rank(jobs, profile)
    logger.info("Scored %d jobs (profile: %d include, %d exclude keywords).",
                len(ranked), len(profile.include_keywords), len(profile.exclude_keywords))
    return {"ranked_jobs": ranked}


def _rank(jobs: list[JobDict], profile: SearchProfile) -> list[RankedJobDict]:
    ranked: list[RankedJobDict] = []
    for job in jobs:
        score = _score_job(job, profile)
        ranked.append({**job, "score": score})
    return sorted(ranked, key=lambda j: j["score"], reverse=True)


def _score_job(job: JobDict, profile: SearchProfile) -> float:
    haystack = (job.get("title", "") + " " + job.get("description_snippet", "")).lower()

    # Disqualify first — no point boosting something we'd reject.
    for kw in profile.exclude_keywords:
        if kw.lower() in haystack:
            return _SCORE_MIN

    # Location filter — only runs when locations are configured and the job has a location.
    # Blank location is treated as unknown and passes through.
    job_location = job.get("location", "")
    if profile.locations and job_location:
        job_loc_lower = job_location.lower()
        if not any(loc.lower() in job_loc_lower for loc in profile.locations):
            return _SCORE_MIN

    score = _SCORE_MIN
    for kw in profile.include_keywords:
        if kw.lower() in haystack:
            score += _INCLUDE_BOOST

    return min(score, _SCORE_MAX)
