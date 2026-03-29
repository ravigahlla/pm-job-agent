"""Tests for generate_for_jobs() and the redact_pii() utility.

No real LLM calls — StubLLM or explicit MagicMock is used throughout.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

from pm_job_agent.agents.generation import generate_for_jobs
from pm_job_agent.models.llm import StubLLM
from pm_job_agent.services.redaction import redact_pii


# ---------------------------------------------------------------------------
# redact_pii()
# ---------------------------------------------------------------------------


class TestRedactPii:
    def test_strips_email(self) -> None:
        assert redact_pii("Contact me at ravi@example.com today.") == (
            "Contact me at [REDACTED] today."
        )

    def test_strips_email_case_insensitive(self) -> None:
        assert "[REDACTED]" in redact_pii("Email: User@DOMAIN.ORG")

    def test_strips_standard_phone(self) -> None:
        assert "[REDACTED]" in redact_pii("Call (415) 555-1234 anytime.")

    def test_strips_dashed_phone(self) -> None:
        assert "[REDACTED]" in redact_pii("Mobile: 415-555-9876")

    def test_strips_dotted_phone(self) -> None:
        assert "[REDACTED]" in redact_pii("415.555.4321")

    def test_strips_street_address(self) -> None:
        result = redact_pii("I live at 123 Main Street, San Francisco.")
        assert "[REDACTED]" in result
        # Non-address content must survive
        assert "San Francisco" in result

    def test_leaves_name_intact(self) -> None:
        result = redact_pii("My name is Ravi Gahlla and I am a PM.")
        assert result == "My name is Ravi Gahlla and I am a PM."

    def test_leaves_url_intact(self) -> None:
        result = redact_pii("See https://linkedin.com/in/ravigahlla for details.")
        assert "linkedin.com" in result

    def test_leaves_company_name_intact(self) -> None:
        result = redact_pii("Worked at Acme Corp as Senior PM.")
        assert result == "Worked at Acme Corp as Senior PM."

    def test_multiple_pii_types_all_redacted(self) -> None:
        text = "Email ravi@test.com or call 415-555-0000. Address: 7 Oak Avenue."
        result = redact_pii(text)
        assert result.count("[REDACTED]") == 3

    def test_empty_string_returns_empty(self) -> None:
        assert redact_pii("") == ""

    def test_no_pii_returns_original(self) -> None:
        text = "Strong background in AI product strategy and roadmap execution."
        assert redact_pii(text) == text


# ---------------------------------------------------------------------------
# generate_for_jobs() — basic behaviour
# ---------------------------------------------------------------------------


def _make_job(job_id: str = "j1", score: float = 0.8) -> dict:
    return {
        "id": job_id,
        "title": "Senior PM",
        "company": "Acme",
        "url": "https://example.com",
        "source": "greenhouse",
        "description_snippet": "Lead AI product strategy.",
        "score": score,
    }


class TestGenerateForJobs:
    def test_returns_one_document_per_job(self) -> None:
        jobs = [_make_job("j1"), _make_job("j2")]
        result = generate_for_jobs(jobs, "PM background.", StubLLM())
        assert len(result) == 2

    def test_document_keyed_by_job_id(self) -> None:
        result = generate_for_jobs([_make_job("abc-123")], "context", StubLLM())
        assert result[0]["job_id"] == "abc-123"
        assert "resume_note" in result[0]
        assert "cover_letter" in result[0]

    def test_empty_jobs_returns_empty_list(self) -> None:
        result = generate_for_jobs([], "context", StubLLM())
        assert result == []

    def test_two_llm_calls_per_job(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Some generated text."
        generate_for_jobs([_make_job("j1"), _make_job("j2")], "context", mock_llm)
        # Two jobs × two calls each = four total
        assert mock_llm.generate.call_count == 4

    def test_pii_in_llm_output_is_redacted(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Contact me at leaked@example.com or 415-555-0001."

        result = generate_for_jobs([_make_job()], "context", mock_llm)

        doc = result[0]
        assert "leaked@example.com" not in doc["resume_note"]
        assert "leaked@example.com" not in doc["cover_letter"]
        assert "[REDACTED]" in doc["resume_note"]

    def test_context_truncated_to_max_chars(self) -> None:
        """LLM should receive only the first 1500 chars of agent context."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "content"
        long_context = "x" * 3000

        generate_for_jobs([_make_job()], long_context, mock_llm)

        # All calls should contain at most the first 1500 chars of the context
        for call_args in mock_llm.generate.call_args_list:
            prompt = call_args[0][0]
            assert "x" * 1501 not in prompt


# ---------------------------------------------------------------------------
# persist integration — resume_note and cover_letter columns in CSV
# ---------------------------------------------------------------------------


class TestPersistWithDocuments:
    def test_documents_appear_in_csv(self, tmp_path: Path) -> None:
        from pm_job_agent.agents.persist import _write_csv

        job = _make_job("j1", 0.8)
        out = tmp_path / "out.csv"
        # Write the initial CSV (empty docs)
        _write_csv(out, [job])

        # Simulate what the generate command does: read, update, write back
        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        rows[0]["resume_note"] = "Emphasise AI PM experience."
        rows[0]["cover_letter"] = "Opening para."

        from pm_job_agent.agents.persist import _COLUMNS
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        with out.open(encoding="utf-8") as fh:
            final_rows = list(csv.DictReader(fh))
        assert final_rows[0]["resume_note"] == "Emphasise AI PM experience."
        assert final_rows[0]["cover_letter"] == "Opening para."

    def test_initial_csv_has_empty_doc_columns(self, tmp_path: Path) -> None:
        from pm_job_agent.agents.persist import _write_csv

        out = tmp_path / "out.csv"
        _write_csv(out, [_make_job()])

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        assert rows[0]["resume_note"] == ""
        assert rows[0]["cover_letter"] == ""
