"""Unit tests for freshness parsing and fallback resolution."""

from __future__ import annotations

from datetime import date, timedelta

from pm_job_agent.services.freshness import parse_source_posted_age_hours, resolve_freshness


def _job(job_id: str, source_posted_at: str = "") -> dict:
    return {
        "id": job_id,
        "title": "PM",
        "company": "Co",
        "url": "https://example.com",
        "source": "test",
        "description_snippet": "AI",
        "source_posted_at": source_posted_at,
    }


class TestParseSourcePostedAgeHours:
    def test_parses_hours_days_and_weeks(self) -> None:
        assert parse_source_posted_age_hours("4 hours ago") == 4.0
        assert parse_source_posted_age_hours("5 days ago") == 120.0
        assert parse_source_posted_age_hours("2 weeks ago") == 336.0

    def test_parses_today_and_just_now(self) -> None:
        assert parse_source_posted_age_hours("today") == 0.0
        assert parse_source_posted_age_hours("just now") == 0.0

    def test_unknown_format_returns_none(self) -> None:
        assert parse_source_posted_age_hours("") is None
        assert parse_source_posted_age_hours("30+ days ago") is None


class TestResolveFreshness:
    def test_prefers_source_posted_at_when_parseable(self) -> None:
        age_hours, basis = resolve_freshness(_job("job:1", "3 days ago"), {})
        assert age_hours == 72.0
        assert basis == "source_posted_at"

    def test_uses_first_seen_fallback_for_unknown_source_date(self) -> None:
        old = (date.today() - timedelta(days=2)).isoformat()
        age_hours, basis = resolve_freshness(_job("job:2", ""), {"job:2": old})
        assert age_hours == 48.0
        assert basis == "first_seen"

    def test_new_unknown_job_defaults_to_zero_hours(self) -> None:
        age_hours, basis = resolve_freshness(_job("job:3", ""), {})
        assert age_hours == 0.0
        assert basis == "first_seen"
