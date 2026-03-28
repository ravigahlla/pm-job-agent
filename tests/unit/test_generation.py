"""Tests for the generation agent and the redact_pii() utility.

No real LLM calls — StubLLM or explicit MagicMock is used throughout.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_job_agent.agents.generation import generate_documents, make_generation_node
from pm_job_agent.config.settings import get_settings
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
# generate_documents() — threshold gating
# ---------------------------------------------------------------------------


def _make_ranked_job(job_id: str = "j1", score: float = 0.8) -> dict:
    return {
        "id": job_id,
        "title": "Senior PM",
        "company": "Acme",
        "url": "https://example.com",
        "source": "greenhouse",
        "description_snippet": "Lead AI product strategy.",
        "score": score,
    }


class TestGenerateDocumentsThreshold:
    def test_jobs_above_threshold_get_documents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        state = {"ranked_jobs": [_make_ranked_job(score=0.8)], "agent_context": "PM background."}
        result = generate_documents(state, llm=StubLLM())

        assert len(result["documents"]) == 1
        assert result["documents"][0]["job_id"] == "j1"

    def test_jobs_below_threshold_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.5")
        get_settings.cache_clear()

        state = {"ranked_jobs": [_make_ranked_job(score=0.2)], "agent_context": "PM background."}
        result = generate_documents(state, llm=StubLLM())

        assert result["documents"] == []

    def test_job_at_exact_threshold_qualifies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.5")
        get_settings.cache_clear()

        state = {"ranked_jobs": [_make_ranked_job(score=0.5)], "agent_context": "context"}
        result = generate_documents(state, llm=StubLLM())

        assert len(result["documents"]) == 1

    def test_empty_ranked_jobs_returns_empty_documents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        result = generate_documents({"ranked_jobs": []}, llm=StubLLM())
        assert result["documents"] == []

    def test_missing_ranked_jobs_key_returns_empty_documents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        result = generate_documents({}, llm=StubLLM())
        assert result["documents"] == []


# ---------------------------------------------------------------------------
# generate_documents() — LLM calls and redaction
# ---------------------------------------------------------------------------


class TestGenerateDocumentsLLMBehaviour:
    def test_two_llm_calls_per_qualifying_job(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Some generated text."
        state = {
            "ranked_jobs": [_make_ranked_job("j1", 0.9), _make_ranked_job("j2", 0.7)],
            "agent_context": "context",
        }
        generate_documents(state, llm=mock_llm)

        # Two jobs × two calls each = four total
        assert mock_llm.generate.call_count == 4

    def test_pii_in_llm_output_is_redacted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        mock_llm = MagicMock()
        # Simulate an LLM that echoes back PII from the context
        mock_llm.generate.return_value = "Contact me at leaked@example.com or 415-555-0001."

        state = {"ranked_jobs": [_make_ranked_job(score=0.8)], "agent_context": "context"}
        result = generate_documents(state, llm=mock_llm)

        doc = result["documents"][0]
        assert "leaked@example.com" not in doc["resume_note"]
        assert "leaked@example.com" not in doc["cover_letter"]
        assert "[REDACTED]" in doc["resume_note"]

    def test_documents_keyed_by_job_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Tailored content."
        state = {
            "ranked_jobs": [_make_ranked_job("abc-123", 0.9)],
            "agent_context": "context",
        }
        result = generate_documents(state, llm=mock_llm)

        assert result["documents"][0]["job_id"] == "abc-123"
        assert "resume_note" in result["documents"][0]
        assert "cover_letter" in result["documents"][0]


# ---------------------------------------------------------------------------
# persist integration — resume_note and cover_letter columns in CSV
# ---------------------------------------------------------------------------


class TestPersistWithDocuments:
    def test_documents_appear_in_csv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pm_job_agent.agents.persist import _write_csv

        job = _make_ranked_job("j1", 0.8)
        documents = [{"job_id": "j1", "resume_note": "Emphasise AI PM experience.", "cover_letter": "Opening para."}]

        out = tmp_path / "out.csv"
        _write_csv(out, [job], documents)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        assert rows[0]["resume_note"] == "Emphasise AI PM experience."
        assert rows[0]["cover_letter"] == "Opening para."

    def test_no_documents_writes_empty_columns(self, tmp_path: Path) -> None:
        from pm_job_agent.agents.persist import _write_csv

        out = tmp_path / "out.csv"
        _write_csv(out, [_make_ranked_job()], documents=None)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        assert rows[0]["resume_note"] == ""
        assert rows[0]["cover_letter"] == ""


# ---------------------------------------------------------------------------
# Full core loop integration — generation node runs end-to-end with StubLLM
# ---------------------------------------------------------------------------


class TestCoreLoopWithGeneration:
    def test_documents_key_in_result(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """With no search profile, ranked_jobs is empty and documents should be []."""
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
        monkeypatch.setenv("MIN_SCORE_FOR_GENERATION", "0.3")
        get_settings.cache_clear()

        from pm_job_agent.graphs import build_core_loop_graph

        app = build_core_loop_graph(llm=StubLLM())
        result = app.invoke({})

        assert "documents" in result
        assert result["documents"] == []
        assert "output_path" in result
