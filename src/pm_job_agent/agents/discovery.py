"""Job discovery from external sources. Phase 1: empty stub; Greenhouse/Adzuna plug in here."""

from __future__ import annotations

from pm_job_agent.graphs.state import CoreLoopState


def discover_jobs(_: CoreLoopState) -> dict:
    return {"jobs": []}
