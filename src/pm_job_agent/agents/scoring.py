"""
Rank jobs against career context. Phase 1: placeholder scores; replace with LLM or rules.
"""

from __future__ import annotations

from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.services.types import RankedJobDict


def score_jobs(state: CoreLoopState) -> dict:
    jobs = state.get("jobs") or []
    ranked: list[RankedJobDict] = []
    for job in jobs:
        ranked.append({**job, "score": 0.5})
    return {"ranked_jobs": ranked}
