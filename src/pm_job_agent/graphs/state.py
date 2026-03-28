"""LangGraph state for the Phase 1 core loop."""

from __future__ import annotations

from typing import TypedDict

from pm_job_agent.services.types import DocumentDict, JobDict, RankedJobDict


class CoreLoopState(TypedDict, total=False):
    agent_context: str
    jobs: list[JobDict]
    ranked_jobs: list[RankedJobDict]
    digest: str
    documents: list[DocumentDict]  # set by generation node; one entry per qualifying job
    output_path: str  # set by persist node; path of the CSV written this run
