"""Tests for the persist node (CSV writer)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pm_job_agent.agents.persist import _COLUMNS, _write_csv, persist_jobs
from pm_job_agent.config.settings import get_settings


def _make_job(title: str = "Senior PM", score: float = 0.6) -> dict:
    return {
        "id": "greenhouse:acme:1",
        "title": title,
        "company": "Acme",
        "location": "Remote",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
        "description_snippet": "Great role for an AI PM.",
        "score": score,
    }


# ---------------------------------------------------------------------------
# _write_csv helper
# ---------------------------------------------------------------------------

class TestWriteCsv:
    def test_writes_header_and_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        _write_csv(path, [_make_job()])

        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["title"] == "Senior PM"
        assert rows[0]["company"] == "Acme"
        assert rows[0]["score"] == "0.6"
        assert rows[0]["location"] == "Remote"

    def test_empty_jobs_writes_header_only(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        _write_csv(path, [])

        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            assert list(reader) == []

    def test_missing_optional_field_written_as_empty_string(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        job = _make_job()
        del job["location"]  # location is optional in JobDict
        _write_csv(path, [job])

        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        assert rows[0]["location"] == ""

    def test_multiple_rows_sorted_by_caller(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        jobs = [_make_job("Role A", score=0.8), _make_job("Role B", score=0.4)]
        _write_csv(path, jobs)

        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        assert len(rows) == 2
        assert rows[0]["title"] == "Role A"
        assert rows[1]["title"] == "Role B"


# ---------------------------------------------------------------------------
# persist_jobs node
# ---------------------------------------------------------------------------

class TestPersistJobs:
    def test_returns_output_path_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        get_settings.cache_clear()

        result = persist_jobs({"ranked_jobs": [_make_job()]})
        assert "output_path" in result
        assert result["output_path"].endswith(".csv")

    def test_creates_output_dir_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nested = tmp_path / "a" / "b" / "outputs"
        monkeypatch.setenv("OUTPUT_DIR", str(nested))
        get_settings.cache_clear()

        persist_jobs({})
        assert nested.exists()

    def test_csv_file_exists_and_is_readable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        get_settings.cache_clear()

        result = persist_jobs({"ranked_jobs": [_make_job("AI PM", score=0.8)]})
        csv_path = Path(result["output_path"])

        assert csv_path.exists()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["title"] == "AI PM"

    def test_empty_state_writes_header_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        get_settings.cache_clear()

        result = persist_jobs({})
        csv_path = Path(result["output_path"])

        with csv_path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            assert list(reader) == []
