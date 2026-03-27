"""LangGraph state for the Phase 1 core loop."""

from __future__ import annotations

from typing import TypedDict

from pm_job_agent.services.types import JobDict, RankedJobDict


class CoreLoopState(TypedDict, total=False):
    agent_context: str
    jobs: list[JobDict]
    ranked_jobs: list[RankedJobDict]
    digest: str
