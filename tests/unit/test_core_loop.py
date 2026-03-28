"""Core LangGraph pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from pm_job_agent.agents.context import load_agent_context
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs import build_core_loop_graph
from pm_job_agent.models.llm import StubLLM
from pm_job_agent.services.types import JobDict


def test_core_loop_with_stub_llm() -> None:
    app = build_core_loop_graph(llm=StubLLM())
    result = app.invoke({})
    assert "digest" in result
    assert "[stub-llm]" in result["digest"]
    assert result.get("ranked_jobs") == []


def test_score_jobs_no_keywords_scores_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With an empty search profile (no keywords), every job scores 0.0."""
    from pm_job_agent.agents.scoring import score_jobs

    # Point settings at a non-existent profile so load_search_profile returns empty SearchProfile.
    monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
    get_settings.cache_clear()

    job: JobDict = {
        "id": "1",
        "title": "PM",
        "company": "Acme",
        "url": "https://example.com",
        "source": "test",
        "description_snippet": "",
    }
    out = score_jobs({"jobs": [job]})
    assert len(out["ranked_jobs"]) == 1
    assert out["ranked_jobs"][0]["score"] == 0.0


def test_load_agent_context_reads_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = tmp_path / "ctx.md"
    ctx.write_text("pm experience", encoding="utf-8")
    monkeypatch.setenv("AGENT_CONTEXT_PATH", str(ctx))
    get_settings.cache_clear()
    out = load_agent_context({})
    assert out["agent_context"] == "pm experience"


def test_load_agent_context_missing_file_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_CONTEXT_PATH", "/nonexistent/agent-context.md")
    get_settings.cache_clear()
    out = load_agent_context({})
    assert out["agent_context"] == ""
