"""Tests for the deduplicate agent node."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pm_job_agent.agents.deduplicate import deduplicate_jobs, make_deduplicate_node
from pm_job_agent.config.settings import Settings, get_settings


def _settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        seen_jobs_path=tmp_path / "seen_jobs.json",
        seen_jobs_ttl_days=60,
        default_llm_provider="stub",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _job(job_id: str, score: float = 0.4) -> dict:
    return {
        "id": job_id,
        "title": "PM",
        "company": "Acme",
        "location": "Remote",
        "url": "https://example.com",
        "source": "test",
        "description_snippet": "",
        "score": score,
    }


# ---------------------------------------------------------------------------
# deduplicate_jobs
# ---------------------------------------------------------------------------

class TestDeduplicateJobs:
    def test_all_new_when_no_seen_file(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        state = {"ranked_jobs": [_job("job:1"), _job("job:2")]}

        result = deduplicate_jobs(state, settings=settings)

        assert set(result["new_job_ids"]) == {"job:1", "job:2"}

    def test_filters_out_previously_seen_ids(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        seen_path = tmp_path / "seen_jobs.json"
        seen_path.write_text(json.dumps({"job:1": "2026-03-01"}))

        state = {"ranked_jobs": [_job("job:1"), _job("job:2")]}
        result = deduplicate_jobs(state, settings=settings)

        assert result["new_job_ids"] == ["job:2"]

    def test_all_seen_returns_empty_list(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        seen_path = tmp_path / "seen_jobs.json"
        seen_path.write_text(json.dumps({"job:1": "2026-03-01", "job:2": "2026-03-01"}))

        state = {"ranked_jobs": [_job("job:1"), _job("job:2")]}
        result = deduplicate_jobs(state, settings=settings)

        assert result["new_job_ids"] == []

    def test_empty_ranked_jobs_returns_empty_new_ids(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = deduplicate_jobs({}, settings=settings)
        assert result["new_job_ids"] == []

    def test_jobs_without_id_field_are_skipped(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        job_no_id = {"title": "PM", "score": 0.4}
        job_with_id = _job("job:1")
        state = {"ranked_jobs": [job_no_id, job_with_id]}

        result = deduplicate_jobs(state, settings=settings)
        assert result["new_job_ids"] == ["job:1"]

    def test_make_deduplicate_node_returns_callable(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        node = make_deduplicate_node(settings)
        assert callable(node)

    def test_node_callable_returns_new_job_ids(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        node = make_deduplicate_node(settings)
        result = node({"ranked_jobs": [_job("job:1")]})
        assert "new_job_ids" in result
        assert "job:1" in result["new_job_ids"]
