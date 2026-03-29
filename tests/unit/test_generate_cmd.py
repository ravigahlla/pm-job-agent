"""Tests for the on-demand generate command.

All tests use StubLLM or MagicMock — no real LLM calls.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_job_agent.agents.persist import _COLUMNS, _write_csv
from pm_job_agent.cli.generate_cmd import run_generate
from pm_job_agent.config.settings import get_settings


def _make_job_row(
    job_id: str = "j1",
    title: str = "Senior PM",
    company: str = "Acme",
    score: float = 0.8,
    flagged: str = "",
) -> dict:
    return {
        "score": str(score),
        "flagged": flagged,
        "title": title,
        "company": company,
        "location": "Remote",
        "url": "https://example.com",
        "source": "greenhouse",
        "id": job_id,
        "description_snippet": "Lead AI product strategy.",
        "resume_note": "",
        "cover_letter": "",
    }


def _write_run_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_run_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Flagged rows get documents; unflagged rows are skipped
# ---------------------------------------------------------------------------


class TestRunGenerate:
    def test_flagged_row_gets_resume_and_cover(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CONTEXT_PATH", str(tmp_path / "no_context.md"))
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()

        csv_path = tmp_path / "run.csv"
        _write_run_csv(csv_path, [_make_job_row(flagged="yes")])

        run_generate(csv_path)

        rows = _read_run_csv(csv_path)
        assert rows[0]["resume_note"] != ""
        assert rows[0]["cover_letter"] != ""

    def test_unflagged_row_is_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CONTEXT_PATH", str(tmp_path / "no_context.md"))
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()

        csv_path = tmp_path / "run.csv"
        _write_run_csv(csv_path, [
            _make_job_row("j1", flagged="yes"),
            _make_job_row("j2", flagged=""),
        ])

        run_generate(csv_path)

        rows = _read_run_csv(csv_path)
        assert rows[0]["resume_note"] != ""   # flagged — filled
        assert rows[1]["resume_note"] == ""   # not flagged — left empty

    def test_flagged_case_insensitive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CONTEXT_PATH", str(tmp_path / "no_context.md"))
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()

        csv_path = tmp_path / "run.csv"
        _write_run_csv(csv_path, [_make_job_row(flagged="YES")])

        run_generate(csv_path)

        rows = _read_run_csv(csv_path)
        assert rows[0]["resume_note"] != ""

    def test_no_flagged_rows_prints_message_and_does_not_modify(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("AGENT_CONTEXT_PATH", str(tmp_path / "no_context.md"))
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()

        csv_path = tmp_path / "run.csv"
        _write_run_csv(csv_path, [_make_job_row(flagged="")])
        original_mtime = csv_path.stat().st_mtime

        run_generate(csv_path)

        captured = capsys.readouterr()
        assert "flagged" in captured.out.lower()
        # File should not have been rewritten (no-op path)
        assert csv_path.stat().st_mtime == original_mtime

    def test_missing_csv_exits_with_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.csv"
        with pytest.raises(SystemExit):
            run_generate(missing)

    def test_all_rows_preserved_after_generation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All rows must be present in the output — generate must not drop non-flagged rows."""
        monkeypatch.setenv("AGENT_CONTEXT_PATH", str(tmp_path / "no_context.md"))
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()

        csv_path = tmp_path / "run.csv"
        _write_run_csv(csv_path, [
            _make_job_row("j1", title="Role A", flagged="yes"),
            _make_job_row("j2", title="Role B", flagged=""),
            _make_job_row("j3", title="Role C", flagged=""),
        ])

        run_generate(csv_path)

        rows = _read_run_csv(csv_path)
        assert len(rows) == 3
        assert rows[0]["title"] == "Role A"
        assert rows[1]["title"] == "Role B"
        assert rows[2]["title"] == "Role C"

    def test_agent_context_loaded_from_settings_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("PM with 12 years experience.", encoding="utf-8")
        monkeypatch.setenv("AGENT_CONTEXT_PATH", str(ctx_file))
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()

        csv_path = tmp_path / "run.csv"
        _write_run_csv(csv_path, [_make_job_row(flagged="yes")])

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Generated content."

        with patch("pm_job_agent.cli.generate_cmd.get_llm_client", return_value=mock_llm):
            run_generate(csv_path)

        # Context text should appear in one of the prompts sent to the LLM
        all_prompts = " ".join(str(call) for call in mock_llm.generate.call_args_list)
        assert "PM with 12 years experience." in all_prompts
