"""Helpers for resolving job freshness from source metadata or first-seen date."""

from __future__ import annotations

import re
from datetime import date

from pm_job_agent.services.types import JobDict

_HOUR_RE = re.compile(r"^\s*(\d+)\s+hours?\s+ago\s*$", re.IGNORECASE)
_DAY_RE = re.compile(r"^\s*(\d+)\s+days?\s+ago\s*$", re.IGNORECASE)
_WEEK_RE = re.compile(r"^\s*(\d+)\s+weeks?\s+ago\s*$", re.IGNORECASE)


def parse_source_posted_age_hours(source_posted_at: str) -> float | None:
    """Parse relative posting text (e.g. '4 days ago') to age in hours."""
    raw = (source_posted_at or "").strip().lower()
    if not raw:
        return None
    if raw in {"just now", "today"}:
        return 0.0

    hour_match = _HOUR_RE.match(raw)
    if hour_match:
        return float(int(hour_match.group(1)))

    day_match = _DAY_RE.match(raw)
    if day_match:
        return float(int(day_match.group(1)) * 24)

    week_match = _WEEK_RE.match(raw)
    if week_match:
        return float(int(week_match.group(1)) * 24 * 7)

    return None


def resolve_freshness(job: JobDict, seen: dict[str, str]) -> tuple[float, str]:
    """Return (age_hours, basis) using source_posted_at first, then first_seen fallback."""
    parsed = parse_source_posted_age_hours(job.get("source_posted_at", ""))
    if parsed is not None:
        return parsed, "source_posted_at"

    first_seen = seen.get(job["id"])
    if first_seen:
        try:
            seen_date = date.fromisoformat(first_seen)
            age_days = max((date.today() - seen_date).days, 0)
            return float(age_days * 24), "first_seen"
        except ValueError:
            pass

    # Unknown + never seen before: treat as newly discovered this run.
    return 0.0, "first_seen"
