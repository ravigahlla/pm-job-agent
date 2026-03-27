"""LangGraph composition."""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "build_core_loop_graph":
        from pm_job_agent.graphs.core_loop import build_core_loop_graph as _fn

        return _fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["build_core_loop_graph"]
