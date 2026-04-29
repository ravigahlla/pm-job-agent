"""Tests for the scoring-v2 LLM semantic scoring pipeline.

All tests use StubLLM or MagicMock — no real LLM calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_job_agent.agents.scoring import (
    _SCORING_SYSTEM_BASE,
    _build_scoring_system,
    _keyword_score,
    _parse_llm_response,
    _passes_pre_filter,
    _score_single,
    make_score_node,
)
from pm_job_agent.config.search_profile import SearchProfile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.models.llm import StubLLM
from pm_job_agent.services.types import JobDict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job(
    title: str = "Senior PM",
    company: str = "Acme",
    description: str = "",
    location: str = "",
) -> JobDict:
    return {
        "id": "test-1",
        "title": title,
        "company": company,
        "url": "https://example.com",
        "source": "test",
        "description_snippet": description,
        "location": location,
    }


def _profile(
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    locations: list[str] | None = None,
) -> SearchProfile:
    return SearchProfile(
        include_keywords=include or [],
        exclude_keywords=exclude or [],
        locations=locations or [],
    )


# ---------------------------------------------------------------------------
# _passes_pre_filter
# ---------------------------------------------------------------------------


class TestPreFilter:
    def test_exclude_keyword_in_title_disqualifies(self) -> None:
        job = _job(title="Intern PM")
        profile = _profile(include=["AI"], exclude=["Intern"])
        passes, reason = _passes_pre_filter(job, profile)
        assert not passes
        assert "Intern" in reason

    def test_exclude_keyword_in_description_disqualifies(self) -> None:
        job = _job(description="This is an internship role")
        profile = _profile(include=["AI"], exclude=["internship"])
        passes, reason = _passes_pre_filter(job, profile)
        assert not passes

    def test_no_include_keyword_match_disqualifies(self) -> None:
        job = _job(title="PM", description="fintech platform")
        profile = _profile(include=["AI", "LLM"])
        passes, reason = _passes_pre_filter(job, profile)
        assert not passes
        assert "No include keywords" in reason

    def test_at_least_one_include_match_passes(self) -> None:
        job = _job(description="AI-powered product")
        profile = _profile(include=["AI", "ML"])
        passes, _ = _passes_pre_filter(job, profile)
        assert passes

    def test_no_include_keywords_configured_passes(self) -> None:
        """Empty include list means no keyword gate — everything passes to LLM."""
        job = _job(title="PM", description="some role")
        profile = _profile(include=[])
        passes, _ = _passes_pre_filter(job, profile)
        assert passes

    def test_location_does_not_disqualify(self) -> None:
        """Keyword pre-filter ignores location; strict geo runs in discovery, not here."""
        job = _job(location="Tokyo, Japan")
        profile = _profile(include=["AI"], locations=["San Francisco"])
        job["description_snippet"] = "AI product manager role"
        passes, reason = _passes_pre_filter(job, profile)
        assert passes, f"Should pass pre-filter; got: {reason}"

    def test_exclude_is_case_insensitive(self) -> None:
        job = _job(title="INTERN product manager")
        profile = _profile(include=["AI"], exclude=["intern"])
        passes, _ = _passes_pre_filter(job, profile)
        assert not passes


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def test_parses_valid_json(self) -> None:
        raw = json.dumps({"score": 0.75, "rationale": "Strong match."})
        result = _parse_llm_response(raw)
        assert result is not None
        score, rationale = result
        assert score == pytest.approx(0.75)
        assert rationale == "Strong match."

    def test_clamps_score_above_one(self) -> None:
        raw = json.dumps({"score": 1.5, "rationale": "Over the top."})
        result = _parse_llm_response(raw)
        assert result is not None
        assert result[0] == pytest.approx(1.0)

    def test_clamps_score_below_zero(self) -> None:
        raw = json.dumps({"score": -0.3, "rationale": "Below zero."})
        result = _parse_llm_response(raw)
        assert result is not None
        assert result[0] == pytest.approx(0.0)

    def test_strips_markdown_code_fence(self) -> None:
        raw = '```json\n{"score": 0.6, "rationale": "Good fit."}\n```'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result[0] == pytest.approx(0.6)

    def test_returns_none_for_garbage(self) -> None:
        assert _parse_llm_response("this is not json at all") is None

    def test_returns_none_when_score_missing(self) -> None:
        raw = json.dumps({"rationale": "No score key."})
        assert _parse_llm_response(raw) is None

    def test_lenient_extraction_from_malformed_json(self) -> None:
        # Model emits something almost-JSON — regex fallback should recover.
        raw = '{"score": 0.8, "rationale": "Solid candidate",}'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result[0] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# _keyword_score  (fallback path)
# ---------------------------------------------------------------------------


class TestKeywordScore:
    def test_no_keywords_scores_zero(self) -> None:
        job = _job(description="PM role at a startup")
        profile = _profile(include=[])
        assert _keyword_score(job, profile) == pytest.approx(0.0)

    def test_two_matches_boost(self) -> None:
        job = _job(description="AI and LLM product manager")
        profile = _profile(include=["AI", "LLM", "fintech"])
        score = _keyword_score(job, profile)
        assert score == pytest.approx(0.4)

    def test_capped_at_one(self) -> None:
        job = _job(description="AI LLM ML fintech b2b saas platform cloud")
        many_keywords = ["AI", "LLM", "ML", "fintech", "b2b", "saas", "platform"]
        profile = _profile(include=many_keywords)
        assert _keyword_score(job, profile) <= 1.0


# ---------------------------------------------------------------------------
# _score_single — integration of pre-filter + LLM
# ---------------------------------------------------------------------------


class TestScoreSingle:
    def test_disqualified_job_scores_zero_no_llm_call(self) -> None:
        mock_llm = MagicMock()
        job = _job(title="Intern PM", description="intern role")
        profile = _profile(include=["AI"], exclude=["intern"])
        result = _score_single(job, profile, mock_llm, context_excerpt="background")
        assert result["score"] == pytest.approx(0.0)
        assert "Excluded" in result.get("score_rationale", "")
        mock_llm.generate.assert_not_called()

    def test_llm_score_used_when_job_passes_pre_filter(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate.return_value = json.dumps(
            {"score": 0.85, "rationale": "Excellent fit."}
        )
        job = _job(description="AI product manager role")
        profile = _profile(include=["AI"])
        result = _score_single(job, profile, mock_llm, context_excerpt="background")
        assert result["score"] == pytest.approx(0.85)
        assert "Excellent fit" in result["score_rationale"]
        mock_llm.generate.assert_called_once()

    def test_falls_back_to_keyword_score_on_parse_failure(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "this is not valid json"
        job = _job(description="AI product manager LLM experience")
        profile = _profile(include=["AI", "LLM"])
        result = _score_single(job, profile, mock_llm, context_excerpt="background")
        # Fallback keyword score: 2 matches × 0.2 = 0.4
        assert result["score"] == pytest.approx(0.4)
        assert "fallback" in result["score_rationale"].lower()

    def test_falls_back_to_keyword_score_on_llm_exception(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("API error")
        job = _job(description="AI product role")
        profile = _profile(include=["AI"])
        result = _score_single(job, profile, mock_llm, context_excerpt="background")
        assert result["score"] == pytest.approx(0.2)
        assert "failed" in result["score_rationale"].lower()

    def test_location_mismatch_does_not_disqualify(self) -> None:
        """Scoring still LLM-scores OOS locations if they reach this node (e.g. soft filter)."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = json.dumps(
            {"score": 0.7, "rationale": "Remote-friendly role."}
        )
        job = _job(description="AI product manager", location="Tokyo, Japan")
        profile = _profile(include=["AI"], locations=["San Francisco"])
        result = _score_single(job, profile, mock_llm, context_excerpt="background")
        assert result["score"] == pytest.approx(0.7)
        mock_llm.generate.assert_called_once()


# ---------------------------------------------------------------------------
# make_score_node — graph node integration
# ---------------------------------------------------------------------------


class TestMakeScoreNode(object):
    def test_node_returns_ranked_jobs_sorted_descending(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        get_settings.cache_clear()

        responses = [
            json.dumps({"score": 0.3, "rationale": "Weak fit."}),
            json.dumps({"score": 0.9, "rationale": "Strong fit."}),
        ]
        call_count = 0

        class SequentialMock:
            def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
                nonlocal call_count
                result = responses[call_count % len(responses)]
                call_count += 1
                return result

        node = make_score_node(SequentialMock())
        state = {
            "agent_context": "PM with AI background",
            "jobs": [
                {
                    "id": "a", "title": "PM A", "company": "Co A",
                    "url": "https://a.com", "source": "test", "description_snippet": "",
                },
                {
                    "id": "b", "title": "PM B", "company": "Co B",
                    "url": "https://b.com", "source": "test", "description_snippet": "",
                },
            ],
        }
        # With no include_keywords configured, both jobs pass pre-filter.
        result = node(state)
        ranked = result["ranked_jobs"]
        assert len(ranked) == 2
        # Higher score must come first.
        assert ranked[0]["score"] >= ranked[1]["score"]

    def test_node_with_stub_llm_falls_back_gracefully(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """StubLLM returns unparseable text — all jobs fall back to keyword score (0.0)."""
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        get_settings.cache_clear()

        node = make_score_node(StubLLM())
        state: dict = {
            "agent_context": "",
            "jobs": [
                {
                    "id": "x", "title": "PM", "company": "C",
                    "url": "https://x.com", "source": "test", "description_snippet": "AI",
                }
            ],
        }
        result = node(state)
        ranked = result["ranked_jobs"]
        assert len(ranked) == 1
        # Stub output is not JSON; fallback score is 0.0 (no include keywords in profile).
        assert ranked[0]["score"] == pytest.approx(0.0)

    def test_node_empty_jobs_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        get_settings.cache_clear()

        node = make_score_node(StubLLM())
        result = node({"jobs": [], "agent_context": ""})
        assert result["ranked_jobs"] == []

    def test_node_prefers_at_or_under_24h_jobs_in_sort_order(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "profile.yaml"))
        (tmp_path / "profile.yaml").write_text(
            "freshness_boost_under_hours: 24\n",
            encoding="utf-8",
        )
        get_settings.cache_clear()

        class StableLlm:
            def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
                return json.dumps({"score": 0.5, "rationale": "Equal fit"})

        node = make_score_node(StableLlm())
        result = node(
            {
                "agent_context": "",
                "jobs": [
                    {
                        "id": "fresh", "title": "Fresh", "company": "Co",
                        "url": "https://a.com", "source": "test", "description_snippet": "",
                        "freshness_age_hours": 24.0,
                    },
                    {
                        "id": "older", "title": "Older", "company": "Co",
                        "url": "https://b.com", "source": "test", "description_snippet": "",
                        "freshness_age_hours": 48.0,
                    },
                ],
            }
        )
        ranked = result["ranked_jobs"]
        assert ranked[0]["id"] == "fresh"


# ---------------------------------------------------------------------------
# _build_scoring_system — criteria injection
# ---------------------------------------------------------------------------

class TestBuildScoringSystem:
    def test_no_criteria_returns_base_prompt(self) -> None:
        """Empty or whitespace-only criteria return the base prompt unchanged."""
        assert _build_scoring_system("") is _SCORING_SYSTEM_BASE
        assert _build_scoring_system("   \n  ") is _SCORING_SYSTEM_BASE

    def test_criteria_appended_to_base_prompt(self) -> None:
        """Non-empty criteria are appended after a consistent separator."""
        criteria = "Prefer B2B SaaS roles. Avoid pure sales-engineering titles."
        result = _build_scoring_system(criteria)
        assert result.startswith(_SCORING_SYSTEM_BASE)
        assert "Candidate-specific scoring criteria" in result
        assert criteria in result

    def test_make_score_node_loads_criteria_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """make_score_node injects criteria into the scoring system prompt when the file exists."""
        criteria_file = tmp_path / "scoring_criteria.md"
        criteria_file.write_text("Prefer early-stage startups. Avoid legacy enterprise.", encoding="utf-8")

        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        monkeypatch.setenv("SCORING_CRITERIA_PATH", str(criteria_file))
        get_settings.cache_clear()

        mock_llm = MagicMock()
        mock_llm.generate.return_value = json.dumps({"score": 0.9, "rationale": "Great fit."})

        node = make_score_node(mock_llm)
        node({
            "agent_context": "",
            "jobs": [
                {"id": "j1", "title": "PM", "company": "StartupCo",
                 "url": "https://x.com", "source": "test", "description_snippet": "AI product"},
            ],
        })

        call_kwargs = mock_llm.generate.call_args
        system_prompt_used = call_kwargs[1].get("system_prompt") or call_kwargs[0][1]
        assert "Prefer early-stage startups" in system_prompt_used

    def test_make_score_node_absent_criteria_file_uses_base(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """make_score_node silently proceeds with base prompt when criteria file is missing."""
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        monkeypatch.setenv("SCORING_CRITERIA_PATH", str(tmp_path / "nonexistent_criteria.md"))
        get_settings.cache_clear()

        mock_llm = MagicMock()
        mock_llm.generate.return_value = json.dumps({"score": 0.5, "rationale": "Decent fit."})

        node = make_score_node(mock_llm)
        node({
            "agent_context": "",
            "jobs": [
                {"id": "j2", "title": "PM", "company": "BigCo",
                 "url": "https://x.com", "source": "test", "description_snippet": "PM role"},
            ],
        })

        call_kwargs = mock_llm.generate.call_args
        system_prompt_used = call_kwargs[1].get("system_prompt") or call_kwargs[0][1]
        assert system_prompt_used == _SCORING_SYSTEM_BASE
