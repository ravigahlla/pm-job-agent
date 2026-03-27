"""Load gitignored career context into graph state."""

from __future__ import annotations

from pm_job_agent.config import get_settings
from pm_job_agent.graphs.state import CoreLoopState


def load_agent_context(_: CoreLoopState) -> dict:
    path = get_settings().agent_context_path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    return {"agent_context": text}
