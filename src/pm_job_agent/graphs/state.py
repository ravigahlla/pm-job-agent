"""LangGraph state for the Phase 1 core loop."""

from __future__ import annotations

from typing import TypedDict

from pm_job_agent.services.types import JobDict, RankedJobDict


class CoreLoopState(TypedDict, total=False):
    agent_context: str
    jobs: list[JobDict]
    ranked_jobs: list[RankedJobDict]
    new_job_ids: list[str]  # set by deduplicate node; IDs not seen in any previous run
    digest: str
    output_path: str  # set by persist node; path of the CSV written this run
