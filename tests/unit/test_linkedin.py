"""Tests for the LinkedIn/Apify integration client and discovery agent LinkedIn branch.

No real Apify calls — ApifyClient is mocked at the boundary throughout.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_job_agent.config.search_profile import SearchProfile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.integrations.linkedin import (
    LinkedInClient,
    LinkedInError,
    _extract_job_id,
    _map_item,
    _title_matches,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_apify_client_mock(items: list[dict], run_id: str = "dataset-123") -> MagicMock:
    """Return a mock ApifyClient whose actor().call() and dataset().iterate_items() work."""
    mock_client = MagicMock()
    mock_run = {"defaultDatasetId": run_id}
    mock_client.actor.return_value.call.return_value = mock_run
    mock_client.dataset.return_value.iterate_items.return_value = iter(items)
    return mock_client


_SAMPLE_ITEMS = [
    {
        "title": "Senior Product Manager",
        "company": "Acme",
        "location": "Remote",
        "jobUrl": "https://www.linkedin.com/jobs/view/1234567890",
        "description": "Lead AI product strategy across the platform.",
    },
    {
        "title": "AI Product Manager",
        "company": "BuildCo",
        "location": "San Francisco",
        "jobUrl": "https://www.linkedin.com/jobs/view/9876543210",
        "description": "Own LLM-powered features end to end.",
    },
    {
        "title": "Project Manager",
        "company": "OtherCorp",
        "location": "New York",
        "jobUrl": "https://www.linkedin.com/jobs/view/1111111111",
        "description": "Manage construction projects.",
    },
]


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

class TestExtractJobId:
    def test_extracts_numeric_id(self) -> None:
        url = "https://www.linkedin.com/jobs/view/1234567890"
        assert _extract_job_id(url) == "1234567890"

    def test_returns_empty_string_for_non_matching_url(self) -> None:
        assert _extract_job_id("https://example.com/something") == ""

    def test_returns_empty_string_for_empty_input(self) -> None:
        assert _extract_job_id("") == ""


class TestTitleMatches:
    def test_matches_when_keyword_present(self) -> None:
        assert _title_matches("Senior Product Manager", ["Product Manager"]) is True

    def test_no_match_returns_false(self) -> None:
        assert _title_matches("Project Manager", ["Product Manager"]) is False

    def test_empty_keywords_always_matches(self) -> None:
        assert _title_matches("Anything", []) is True

    def test_case_insensitive(self) -> None:
        assert _title_matches("SENIOR PM", ["senior pm"]) is True


class TestMapItem:
    def test_maps_standard_fields(self) -> None:
        item = {
            "title": "Senior PM",
            "company": "Acme",
            "location": "Remote",
            "jobUrl": "https://www.linkedin.com/jobs/view/1234567890",
            "description": "Own roadmap.",
        }
        job = _map_item(item)
        assert job is not None
        assert job["id"] == "linkedin:1234567890"
        assert job["title"] == "Senior PM"
        assert job["company"] == "Acme"
        assert job["location"] == "Remote"
        assert job["url"] == "https://www.linkedin.com/jobs/view/1234567890"
        assert job["source"] == "linkedin"
        assert job["description_snippet"] == "Own roadmap."
        assert job.get("source_posted_at", "") == ""
        assert job.get("source_scraped_at", "") == ""

    def test_maps_posted_at_and_scraped_at(self) -> None:
        item = {
            "title": "PM",
            "company": "Co",
            "jobUrl": "https://www.linkedin.com/jobs/view/42",
            "description": "x",
            "postedAt": "2 weeks ago",
            "scrapedAt": "2026-04-01T12:00:00.000Z",
        }
        job = _map_item(item)
        assert job is not None
        assert job["source_posted_at"] == "2 weeks ago"
        assert job["source_scraped_at"] == "2026-04-01T12:00:00.000Z"

    def test_accepts_companyname_field(self) -> None:
        item = {
            "title": "PM",
            "companyName": "AltCo",
            "jobUrl": "https://www.linkedin.com/jobs/view/111",
            "description": "",
        }
        job = _map_item(item)
        assert job is not None
        assert job["company"] == "AltCo"

    def test_description_truncated_to_500_chars(self) -> None:
        item = {
            "title": "PM",
            "company": "Co",
            "jobUrl": "https://www.linkedin.com/jobs/view/999",
            "description": "x" * 1000,
        }
        job = _map_item(item)
        assert job is not None
        assert len(job["description_snippet"]) == 500

    def test_returns_none_when_title_missing(self) -> None:
        item = {"company": "Co", "jobUrl": "https://www.linkedin.com/jobs/view/999"}
        assert _map_item(item) is None

    def test_returns_none_when_url_missing(self) -> None:
        item = {"title": "PM", "company": "Co"}
        assert _map_item(item) is None

    def test_returns_none_when_job_id_not_extractable(self) -> None:
        item = {
            "title": "PM",
            "company": "Co",
            "jobUrl": "https://www.linkedin.com/company/acme",
        }
        assert _map_item(item) is None


# ---------------------------------------------------------------------------
# LinkedInClient.fetch_jobs
# ---------------------------------------------------------------------------

class TestLinkedInClientFetchJobs:
    def test_happy_path_returns_mapped_jobs(self) -> None:
        mock_client = _make_apify_client_mock(_SAMPLE_ITEMS)

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            jobs = client.fetch_jobs("Product Manager", title_keywords=[])

        assert len(jobs) == 3

    def test_title_filtering_drops_non_matching(self) -> None:
        mock_client = _make_apify_client_mock(_SAMPLE_ITEMS)

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            jobs = client.fetch_jobs("Product Manager", title_keywords=["Product Manager"])

        titles = [j["title"] for j in jobs]
        assert "Senior Product Manager" in titles
        assert "AI Product Manager" in titles
        assert "Project Manager" not in titles

    def test_jobs_have_linkedin_source(self) -> None:
        mock_client = _make_apify_client_mock([_SAMPLE_ITEMS[0]])

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            jobs = client.fetch_jobs("PM", title_keywords=[])

        assert jobs[0]["source"] == "linkedin"

    def test_jobs_have_linkedin_prefixed_id(self) -> None:
        mock_client = _make_apify_client_mock([_SAMPLE_ITEMS[0]])

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            jobs = client.fetch_jobs("PM", title_keywords=[])

        assert jobs[0]["id"].startswith("linkedin:")

    def test_items_missing_required_fields_are_skipped(self) -> None:
        bad_items = [
            {"company": "Co"},  # no title, no url
            _SAMPLE_ITEMS[0],   # valid
        ]
        mock_client = _make_apify_client_mock(bad_items)

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            jobs = client.fetch_jobs("PM", title_keywords=[])

        assert len(jobs) == 1

    def test_empty_actor_results_returns_empty_list(self) -> None:
        mock_client = _make_apify_client_mock([])

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            jobs = client.fetch_jobs("PM", title_keywords=[])

        assert jobs == []

    def test_actor_call_failure_raises_linkedin_error(self) -> None:
        mock_client = MagicMock()
        mock_client.actor.return_value.call.side_effect = Exception("network timeout")

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            with pytest.raises(LinkedInError, match="Apify Actor call failed"):
                client.fetch_jobs("PM", title_keywords=[])

    def test_actor_returns_none_raises_linkedin_error(self) -> None:
        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = None

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            with pytest.raises(LinkedInError, match="no run object"):
                client.fetch_jobs("PM", title_keywords=[])

    def test_passes_max_results_to_actor(self) -> None:
        mock_client = _make_apify_client_mock([])

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token", max_results=10)
            client.fetch_jobs("PM", title_keywords=[])

        call_kwargs = mock_client.actor.return_value.call.call_args
        run_input = call_kwargs[1]["run_input"]
        assert run_input["maxResults"] == 10

    def test_passes_apify_geo_and_date_from_profile(self) -> None:
        mock_client = _make_apify_client_mock([])
        profile = SearchProfile(
            linkedin_location="San Francisco Bay Area",
            linkedin_date_posted="r86400",
            linkedin_sort_by="DD",
        )

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            client.fetch_jobs("PM", title_keywords=[], profile=profile)

        run_input = mock_client.actor.return_value.call.call_args[1]["run_input"]
        assert run_input["location"] == "San Francisco Bay Area"
        assert run_input["datePosted"] == "r86400"
        assert run_input["sortBy"] == "DD"

    def test_dateposted_omitted_when_all(self) -> None:
        mock_client = _make_apify_client_mock([])
        profile = SearchProfile(linkedin_date_posted="all")

        with patch("apify_client.ApifyClient", return_value=mock_client):
            client = LinkedInClient(api_token="fake-token")
            client.fetch_jobs("PM", title_keywords=[], profile=profile)

        run_input = mock_client.actor.return_value.call.call_args[1]["run_input"]
        assert "datePosted" not in run_input


# ---------------------------------------------------------------------------
# Discovery agent — LinkedIn branch behaviour
# ---------------------------------------------------------------------------

class TestDiscoveryLinkedInBranch:
    def test_linkedin_skipped_when_no_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No APIFY_API_TOKEN → LinkedIn branch silently skipped, no crash."""
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(tmp_path / "no_profile.yaml"))
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        get_settings.cache_clear()

        from pm_job_agent.agents.discovery import discover_jobs

        result = discover_jobs({})
        assert result == {"jobs": []}

    def test_linkedin_skipped_when_no_search_queries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """APIFY_API_TOKEN set but no linkedin_search_queries → LinkedIn skipped."""
        profile_yaml = tmp_path / "profile.yaml"
        profile_yaml.write_text("linkedin_search_queries: []\n", encoding="utf-8")
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(profile_yaml))
        monkeypatch.setenv("APIFY_API_TOKEN", "fake-token")
        get_settings.cache_clear()

        from pm_job_agent.agents.discovery import discover_jobs

        result = discover_jobs({})
        assert result == {"jobs": []}

    def test_linkedin_jobs_merged_with_greenhouse_dedup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Jobs from LinkedIn and Greenhouse are merged; same ID appears only once."""
        profile_yaml = tmp_path / "profile.yaml"
        profile_yaml.write_text(
            "linkedin_search_queries:\n  - 'Product Manager'\n"
            "greenhouse_board_tokens:\n  - testco\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(profile_yaml))
        monkeypatch.setenv("APIFY_API_TOKEN", "fake-token")
        get_settings.cache_clear()

        li_job = {
            "title": "AI PM",
            "company": "TechCo",
            "location": "Remote",
            "jobUrl": "https://www.linkedin.com/jobs/view/9999",
            "description": "LLM product role.",
        }
        mock_apify = _make_apify_client_mock([li_job])

        from pm_job_agent.agents.discovery import discover_jobs
        from pm_job_agent.integrations.greenhouse import GreenhouseError

        with (
            patch("apify_client.ApifyClient", return_value=mock_apify),
            patch(
                "pm_job_agent.integrations.greenhouse.GreenhouseClient.fetch_jobs",
                side_effect=GreenhouseError("board not found"),
            ),
        ):
            result = discover_jobs({})

        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["source"] == "linkedin"
        assert result["jobs"][0]["id"] == "linkedin:9999"

    def test_strict_location_drops_out_of_area_before_scoring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Beverly Hills must not appear when profile only lists Bay Area substrings."""
        profile_yaml = tmp_path / "profile.yaml"
        profile_yaml.write_text(
            "linkedin_search_queries:\n  - 'Product Manager'\n"
            "location_filter: strict\n"
            "locations:\n  - 'San Francisco'\n  - 'Oakland'\n  - 'Remote'\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SEARCH_PROFILE_PATH", str(profile_yaml))
        monkeypatch.setenv("APIFY_API_TOKEN", "fake-token")
        get_settings.cache_clear()

        li_job = {
            "title": "Principal PM",
            "company": "OP",
            "location": "Beverly Hills, CA",
            "jobUrl": "https://www.linkedin.com/jobs/view/4242",
            "description": "AI strategy.",
        }
        mock_apify = _make_apify_client_mock([li_job])

        from pm_job_agent.agents.discovery import discover_jobs

        with patch("apify_client.ApifyClient", return_value=mock_apify):
            result = discover_jobs({})

        assert result["jobs"] == []


# ---------------------------------------------------------------------------
# SearchProfile: linkedin_search_queries loads from YAML
# ---------------------------------------------------------------------------

class TestSearchProfileLinkedIn:
    def test_loads_linkedin_search_queries(self, tmp_path: Path) -> None:
        from pm_job_agent.config.search_profile import load_search_profile

        yaml_content = (
            "linkedin_search_queries:\n"
            "  - 'AI Product Manager'\n"
            "  - 'Senior PM'\n"
        )
        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(yaml_content, encoding="utf-8")

        profile = load_search_profile(profile_path)
        assert profile.linkedin_search_queries == ["AI Product Manager", "Senior PM"]

    def test_missing_field_defaults_to_empty_list(self, tmp_path: Path) -> None:
        from pm_job_agent.config.search_profile import load_search_profile

        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text("target_titles:\n  - PM\n", encoding="utf-8")

        profile = load_search_profile(profile_path)
        assert profile.linkedin_search_queries == []

    def test_loads_linkedin_actor_and_location_filter_fields(self, tmp_path: Path) -> None:
        from pm_job_agent.config.search_profile import load_search_profile

        profile_path = tmp_path / "profile.yaml"
        profile_path.write_text(
            "location_filter: soft\n"
            "linkedin_location: 'Austin, TX'\n"
            "linkedin_date_posted: r2592000\n"
            "linkedin_sort_by: R\n",
            encoding="utf-8",
        )
        profile = load_search_profile(profile_path)
        assert profile.location_filter == "soft"
        assert profile.linkedin_location == "Austin, TX"
        assert profile.linkedin_date_posted == "r2592000"
        assert profile.linkedin_sort_by == "R"
