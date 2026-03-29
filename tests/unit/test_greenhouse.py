"""Tests for the Greenhouse integration client and keyword-based scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pm_job_agent.agents.scoring import _score_job
from pm_job_agent.config.search_profile import SearchProfile, load_search_profile
from pm_job_agent.integrations.greenhouse import GreenhouseClient, GreenhouseError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, body: dict[str, Any]) -> MagicMock:
    """Build a fake httpx.Response with .status_code and .json()."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    return mock


_SAMPLE_JOBS_PAYLOAD = {
    "jobs": [
        {
            "id": 101,
            "title": "Senior Product Manager",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/101",
            "location": {"name": "Remote"},
            "content": "<p>Looking for an experienced PM with <b>AI</b> background.</p>",
        },
        {
            "id": 102,
            "title": "Marketing Manager",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/102",
            "location": {"name": "New York"},
            "content": "<p>Drive go-to-market campaigns.</p>",
        },
        {
            "id": 103,
            "title": "AI Product Manager",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/103",
            "location": {"name": "San Francisco"},
            "content": "<p>Own our LLM-based product surface.</p>",
        },
    ]
}


# ---------------------------------------------------------------------------
# GreenhouseClient: happy path
# ---------------------------------------------------------------------------

class TestGreenhouseClientFetchJobs:
    def test_filters_by_title_keyword(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE_JOBS_PAYLOAD)):
            client = GreenhouseClient()
            jobs = client.fetch_jobs("testco", title_keywords=["Product Manager"])

        titles = [j["title"] for j in jobs]
        assert "Senior Product Manager" in titles
        assert "AI Product Manager" in titles
        assert "Marketing Manager" not in titles

    def test_returns_all_jobs_when_no_keywords(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE_JOBS_PAYLOAD)):
            client = GreenhouseClient()
            jobs = client.fetch_jobs("testco", title_keywords=[])

        assert len(jobs) == 3

    def test_maps_fields_to_job_dict(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE_JOBS_PAYLOAD)):
            client = GreenhouseClient()
            jobs = client.fetch_jobs("testco", title_keywords=["Senior Product Manager"])

        assert len(jobs) == 1
        job = jobs[0]
        assert job["id"] == "greenhouse:testco:101"
        assert job["title"] == "Senior Product Manager"
        assert job["company"] == "testco"
        assert job["source"] == "greenhouse"
        assert job["url"] == "https://boards.greenhouse.io/testco/jobs/101"
        assert job["location"] == "Remote"
        # HTML tags should be stripped from description_snippet
        assert "<p>" not in job["description_snippet"]
        assert "AI" in job["description_snippet"]

    def test_empty_jobs_list(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, {"jobs": []})):
            client = GreenhouseClient()
            jobs = client.fetch_jobs("testco", title_keywords=["PM"])

        assert jobs == []


# ---------------------------------------------------------------------------
# GreenhouseClient: error cases
# ---------------------------------------------------------------------------

class TestGreenhouseClientErrors:
    def test_raises_greenhouse_error_on_404(self) -> None:
        with patch("httpx.get", return_value=_mock_response(404, {})):
            client = GreenhouseClient()
            with pytest.raises(GreenhouseError, match="HTTP 404"):
                client.fetch_jobs("nonexistent-board", title_keywords=[])

    def test_raises_greenhouse_error_on_network_failure(self) -> None:
        import httpx as _httpx

        with patch("httpx.get", side_effect=_httpx.RequestError("connection refused")):
            client = GreenhouseClient()
            with pytest.raises(GreenhouseError, match="Network error"):
                client.fetch_jobs("testco", title_keywords=[])


# ---------------------------------------------------------------------------
# SearchProfile: load from YAML
# ---------------------------------------------------------------------------

class TestLoadSearchProfile:
    def test_loads_all_fields(self, tmp_path: Path) -> None:
        yaml_content = """
target_titles:
  - "Product Manager"
  - "Senior PM"
locations:
  - "Remote"
include_keywords:
  - "AI"
  - "SaaS"
exclude_keywords:
  - "Intern"
greenhouse_board_tokens:
  - anthropic
  - linear
"""
        profile_path = tmp_path / "search_profile.yaml"
        profile_path.write_text(yaml_content, encoding="utf-8")
        profile = load_search_profile(profile_path)

        assert profile.target_titles == ["Product Manager", "Senior PM"]
        assert profile.locations == ["Remote"]
        assert profile.include_keywords == ["AI", "SaaS"]
        assert profile.exclude_keywords == ["Intern"]
        assert profile.greenhouse_board_tokens == ["anthropic", "linear"]

    def test_missing_file_returns_empty_profile(self, tmp_path: Path) -> None:
        profile = load_search_profile(tmp_path / "nonexistent.yaml")
        assert profile.target_titles == []
        assert profile.greenhouse_board_tokens == []

    def test_empty_yaml_returns_empty_profile(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "search_profile.yaml"
        profile_path.write_text("", encoding="utf-8")
        profile = load_search_profile(profile_path)
        assert profile.include_keywords == []


# ---------------------------------------------------------------------------
# Keyword scoring
# ---------------------------------------------------------------------------

class TestScoreJob:
    def _job(self, title: str = "PM", snippet: str = "") -> dict:
        return {
            "id": "1",
            "title": title,
            "company": "Acme",
            "url": "https://example.com",
            "source": "test",
            "description_snippet": snippet,
        }

    def test_no_keywords_scores_zero(self) -> None:
        profile = SearchProfile()
        assert _score_job(self._job(), profile) == 0.0

    def test_include_keyword_in_title_boosts_score(self) -> None:
        profile = SearchProfile(include_keywords=["AI"])
        score = _score_job(self._job(title="AI Product Manager"), profile)
        assert score == pytest.approx(0.2)

    def test_include_keyword_in_description_boosts_score(self) -> None:
        profile = SearchProfile(include_keywords=["LLM"])
        score = _score_job(self._job(snippet="Owns LLM roadmap"), profile)
        assert score == pytest.approx(0.2)

    def test_multiple_keywords_accumulate(self) -> None:
        profile = SearchProfile(include_keywords=["AI", "SaaS", "platform"])
        score = _score_job(self._job(title="AI Product Manager", snippet="SaaS platform"), profile)
        assert score == pytest.approx(0.6)

    def test_score_capped_at_one(self) -> None:
        profile = SearchProfile(include_keywords=["a", "b", "c", "d", "e", "f"])
        score = _score_job(self._job(title="a b c d e f"), profile)
        assert score == pytest.approx(1.0)

    def test_exclude_keyword_zeroes_score(self) -> None:
        profile = SearchProfile(
            include_keywords=["AI", "SaaS"],
            exclude_keywords=["Intern"],
        )
        score = _score_job(self._job(title="AI Product Manager Intern"), profile)
        assert score == 0.0

    def test_exclude_keyword_case_insensitive(self) -> None:
        profile = SearchProfile(exclude_keywords=["intern"])
        score = _score_job(self._job(title="Product Intern"), profile)
        assert score == 0.0

    def test_include_keyword_case_insensitive(self) -> None:
        profile = SearchProfile(include_keywords=["saas"])
        score = _score_job(self._job(snippet="Built a SaaS product"), profile)
        assert score == pytest.approx(0.2)

    # --- location filtering ---

    def test_matching_location_does_not_affect_score(self) -> None:
        profile = SearchProfile(include_keywords=["AI"], locations=["Remote"])
        score = _score_job(self._job(title="AI PM"), profile)
        # No location on the base job — passes through unchanged
        assert score == pytest.approx(0.2)

    def test_job_location_matches_configured_location(self) -> None:
        profile = SearchProfile(include_keywords=["AI"], locations=["Remote"])
        job = {**self._job(title="AI PM"), "location": "Remote"}
        assert _score_job(job, profile) == pytest.approx(0.2)

    def test_job_location_substring_match(self) -> None:
        """'San Francisco' should match 'San Francisco, CA'."""
        profile = SearchProfile(locations=["San Francisco"])
        job = {**self._job(), "location": "San Francisco, CA"}
        assert _score_job(job, profile) == pytest.approx(0.0)  # no include kws, but not disqualified

    def test_job_location_no_match_zeroes_score(self) -> None:
        profile = SearchProfile(include_keywords=["AI"], locations=["Remote"])
        job = {**self._job(title="AI PM"), "location": "New York, NY"}
        assert _score_job(job, profile) == 0.0

    def test_empty_locations_skips_location_filter(self) -> None:
        """locations = [] means no location filtering — existing behaviour preserved."""
        profile = SearchProfile(include_keywords=["AI"], locations=[])
        job = {**self._job(title="AI PM"), "location": "New York, NY"}
        assert _score_job(job, profile) == pytest.approx(0.2)

    def test_blank_job_location_not_disqualified(self) -> None:
        """A job with no location field passes through even if locations are configured."""
        profile = SearchProfile(include_keywords=["AI"], locations=["Remote"])
        job = {**self._job(title="AI PM"), "location": ""}
        assert _score_job(job, profile) == pytest.approx(0.2)

    def test_location_filter_case_insensitive(self) -> None:
        profile = SearchProfile(locations=["remote"])
        job = {**self._job(), "location": "Remote"}
        # Matches — score is 0.0 only because no include keywords, not because of location
        assert _score_job(job, profile) == pytest.approx(0.0)
        # Now confirm it would NOT be 0 from location disqualification:
        profile_with_kw = SearchProfile(include_keywords=["PM"], locations=["remote"])
        job2 = {**self._job(title="Senior PM"), "location": "Remote"}
        assert _score_job(job2, profile_with_kw) == pytest.approx(0.2)
