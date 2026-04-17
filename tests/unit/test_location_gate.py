"""Tests for search profile strict location gate."""

from __future__ import annotations

from pm_job_agent.config.search_profile import SearchProfile, job_passes_location_gate
from pm_job_agent.services.types import JobDict


def _job(location: str = "") -> JobDict:
    return {
        "id": "test:1",
        "title": "PM",
        "company": "Co",
        "url": "https://example.com",
        "source": "test",
        "description_snippet": "AI",
        "location": location,
    }


class TestJobPassesLocationGate:
    def test_soft_always_passes_with_locations(self) -> None:
        profile = SearchProfile(
            locations=["San Francisco"],
            location_filter="soft",
        )
        ok, reason = job_passes_location_gate(_job("Beverly Hills, CA"), profile)
        assert ok and reason == ""

    def test_strict_empty_locations_always_passes(self) -> None:
        profile = SearchProfile(locations=[], location_filter="strict")
        ok, _ = job_passes_location_gate(_job("Tokyo"), profile)
        assert ok

    def test_strict_blank_job_location_passes(self) -> None:
        profile = SearchProfile(locations=["San Francisco"], location_filter="strict")
        ok, _ = job_passes_location_gate(_job(""), profile)
        assert ok

    def test_strict_substring_match_passes(self) -> None:
        profile = SearchProfile(
            locations=["San Francisco", "Remote"],
            location_filter="strict",
        )
        ok, _ = job_passes_location_gate(_job("San Francisco Bay Area"), profile)
        assert ok

    def test_strict_beverly_hills_fails(self) -> None:
        profile = SearchProfile(locations=["San Francisco", "Remote"], location_filter="strict")
        ok, reason = job_passes_location_gate(_job("Beverly Hills, CA"), profile)
        assert not ok
        assert "strict location" in reason.lower()

    def test_strict_case_insensitive(self) -> None:
        profile = SearchProfile(locations=["remote"], location_filter="strict")
        ok, _ = job_passes_location_gate(_job("REMOTE - US"), profile)
        assert ok

