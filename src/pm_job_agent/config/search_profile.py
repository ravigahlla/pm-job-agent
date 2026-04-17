"""Search criteria for job discovery and scoring.

Loaded from a YAML file (default: private/search_profile.yaml, gitignored).
Copy private/search_profile.yaml.example to private/search_profile.yaml and fill in your targets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pm_job_agent.services.types import JobDict


@dataclass
class SearchProfile:
    # Title keywords: a job is a candidate if its title contains any of these (case-insensitive).
    target_titles: list[str] = field(default_factory=list)

    # Substrings to match against job location when location_filter is strict (case-insensitive).
    # Example Bay Area coverage: "San Francisco", "Oakland", "San Jose", "Bay Area", "Remote".
    # Empty list = no substring location gate (regardless of location_filter).
    locations: list[str] = field(default_factory=list)

    # strict: non-empty job locations must contain at least one entry from `locations`
    #         (blank/unknown location still passes — LLM may still weigh geography).
    # soft:  no substring gate; only the scoring LLM sees location (legacy v2 behaviour).
    location_filter: str = "strict"

    # Words that boost fit score when found in title or description snippet.
    include_keywords: list[str] = field(default_factory=list)

    # Words that immediately disqualify a role (score → 0) when found in title or description.
    exclude_keywords: list[str] = field(default_factory=list)

    # Greenhouse board tokens to query (one per target company, e.g. "anthropic", "linear").
    # Find a company's token at the end of their Greenhouse board URL:
    #   https://boards.greenhouse.io/<token>/
    greenhouse_board_tokens: list[str] = field(default_factory=list)

    # LinkedIn search queries for the Apify integration. Each string is sent as a keyword
    # search to LinkedIn Jobs (via the automation-lab/linkedin-jobs-scraper Actor). Leave
    # empty to skip LinkedIn entirely. Requires APIFY_API_TOKEN to be set in .env.
    linkedin_search_queries: list[str] = field(default_factory=list)

    # Passed to the Apify actor as `location` (LinkedIn geo filter). Empty = omit (global search).
    linkedin_location: str = ""

    # Actor `datePosted`: r86400 | r604800 | r2592000 | "all" (see Apify actor docs).
    linkedin_date_posted: str = "r604800"

    # Actor `sortBy`: "DD" = newest first, "R" = relevance (actor default).
    linkedin_sort_by: str = "DD"

    # Lever board slugs to query (one per target company, e.g. "notion", "ramp").
    # Find a company's slug at the end of their Lever board URL:
    #   https://jobs.lever.co/<slug>/
    # No API key required — Lever's public board API is unauthenticated.
    lever_board_tokens: list[str] = field(default_factory=list)


def job_passes_location_gate(job: JobDict, profile: SearchProfile) -> tuple[bool, str]:
    """Return (True, '') if the job should be kept for discovery → scoring.

    When ``location_filter`` is ``strict`` and ``locations`` is non-empty, a job with a
    non-empty ``location`` must contain at least one profile term as a substring
    (case-insensitive). Blank job location always passes so ambiguous listings are not
    dropped before the LLM sees them.
    """
    if profile.location_filter != "strict" or not profile.locations:
        return True, ""
    raw = (job.get("location") or "").strip()
    if not raw:
        return True, ""
    lowered = raw.lower()
    for term in profile.locations:
        if term.lower() in lowered:
            return True, ""
    return False, f"Excluded by strict location filter (job location: {raw!r})"


def load_search_profile(path: Path) -> SearchProfile:
    """Load a SearchProfile from a YAML file. Missing file returns an empty profile (no crash)."""
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load search_profile.yaml. "
            "Run: pip install pyyaml"
        ) from exc

    if not path.exists():
        return SearchProfile()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    loc_filter = (raw.get("location_filter") or "strict").strip().lower()
    if loc_filter not in ("strict", "soft"):
        loc_filter = "strict"

    return SearchProfile(
        target_titles=raw.get("target_titles") or [],
        locations=raw.get("locations") or [],
        location_filter=loc_filter,
        include_keywords=raw.get("include_keywords") or [],
        exclude_keywords=raw.get("exclude_keywords") or [],
        greenhouse_board_tokens=raw.get("greenhouse_board_tokens") or [],
        linkedin_search_queries=raw.get("linkedin_search_queries") or [],
        linkedin_location=(raw.get("linkedin_location") or "").strip(),
        linkedin_date_posted=(raw.get("linkedin_date_posted") or "r604800").strip(),
        linkedin_sort_by=(raw.get("linkedin_sort_by") or "DD").strip(),
        lever_board_tokens=raw.get("lever_board_tokens") or [],
    )
