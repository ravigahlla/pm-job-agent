"""Search criteria for job discovery and scoring.

Loaded from a YAML file (default: private/search_profile.yaml, gitignored).
Copy private/search_profile.yaml.example to private/search_profile.yaml and fill in your targets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SearchProfile:
    # Title keywords: a job is a candidate if its title contains any of these (case-insensitive).
    target_titles: list[str] = field(default_factory=list)

    # Location filter words (e.g. "Remote", "San Francisco"). Empty list = no location filter.
    locations: list[str] = field(default_factory=list)

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

    # Lever board slugs to query (one per target company, e.g. "notion", "ramp").
    # Find a company's slug at the end of their Lever board URL:
    #   https://jobs.lever.co/<slug>/
    # No API key required — Lever's public board API is unauthenticated.
    lever_board_tokens: list[str] = field(default_factory=list)


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
    return SearchProfile(
        target_titles=raw.get("target_titles") or [],
        locations=raw.get("locations") or [],
        include_keywords=raw.get("include_keywords") or [],
        exclude_keywords=raw.get("exclude_keywords") or [],
        greenhouse_board_tokens=raw.get("greenhouse_board_tokens") or [],
        linkedin_search_queries=raw.get("linkedin_search_queries") or [],
        lever_board_tokens=raw.get("lever_board_tokens") or [],
    )
