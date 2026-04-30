"""Search criteria for job discovery and scoring.

Loaded from a YAML file (default: private/search_profile.yaml, gitignored).
Copy private/search_profile.yaml.example to private/search_profile.yaml and fill in your targets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pm_job_agent.services.types import JobDict

logger = logging.getLogger(__name__)


@dataclass
class EmployerBoards:
    """One logical employer and the ATS board slug(s) to query."""

    name: str
    greenhouse: str | None = None
    lever: str | None = None
    ashby: str | None = None


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

    # Preferred: unified list — one row per employer with optional greenhouse / lever / ashby keys.
    # When non-empty, YAML ``target_employers`` was set (legacy three-list keys are ignored for boards).
    target_employers: list[EmployerBoards] = field(default_factory=list)

    # Derived from ``target_employers`` order for backwards compatibility / introspection.
    greenhouse_board_tokens: list[str] = field(default_factory=list)
    lever_board_tokens: list[str] = field(default_factory=list)
    ashby_board_names: list[str] = field(default_factory=list)

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

    # Hard freshness gate for discovery: drop jobs older than this many days.
    freshness_max_days: int = 5

    # Recency preference in ranking: jobs fresher than this threshold are boosted.
    freshness_boost_under_hours: int = 24


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_employer_row(item: Any, index: int) -> EmployerBoards | None:
    if not isinstance(item, dict):
        logger.warning("target_employers[%d] is not a mapping — skipping.", index)
        return None
    gh = _opt_str(item.get("greenhouse"))
    lv = _opt_str(item.get("lever"))
    ab = _opt_str(item.get("ashby"))
    if not gh and not lv and not ab:
        logger.warning(
            "target_employers[%d] has no greenhouse, lever, or ashby slug — skipping.", index
        )
        return None
    name = _opt_str(item.get("name"))
    if not name:
        name = gh or lv or ab
    return EmployerBoards(name=name, greenhouse=gh, lever=lv, ashby=ab)


def _target_employers_from_explicit(raw_list: list[Any]) -> list[EmployerBoards]:
    out: list[EmployerBoards] = []
    for i, item in enumerate(raw_list):
        row = _parse_employer_row(item, i)
        if row is not None:
            out.append(row)
    return out


def _target_employers_from_legacy(raw: dict[str, Any]) -> list[EmployerBoards]:
    out: list[EmployerBoards] = []
    for t in raw.get("greenhouse_board_tokens") or []:
        s = _opt_str(t)
        if s:
            out.append(EmployerBoards(name=s, greenhouse=s))
    for t in raw.get("lever_board_tokens") or []:
        s = _opt_str(t)
        if s:
            out.append(EmployerBoards(name=s, lever=s))
    for t in raw.get("ashby_board_names") or []:
        s = _opt_str(t)
        if s:
            out.append(EmployerBoards(name=s, ashby=s))
    return out


def resolve_target_employers(raw: dict[str, Any]) -> list[EmployerBoards]:
    """Build target list: non-empty ``target_employers`` wins; else legacy three lists."""
    explicit = raw.get("target_employers")
    if isinstance(explicit, list) and len(explicit) > 0:
        return _target_employers_from_explicit(explicit)
    return _target_employers_from_legacy(raw)


def _derive_board_lists(employers: list[EmployerBoards]) -> tuple[list[str], list[str], list[str]]:
    gh: list[str] = []
    lv: list[str] = []
    ab: list[str] = []
    for emp in employers:
        if emp.greenhouse:
            gh.append(emp.greenhouse)
        if emp.lever:
            lv.append(emp.lever)
        if emp.ashby:
            ab.append(emp.ashby)
    return gh, lv, ab


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

    target_employers = resolve_target_employers(raw)
    gh_tokens, lv_tokens, ab_names = _derive_board_lists(target_employers)

    return SearchProfile(
        target_titles=raw.get("target_titles") or [],
        locations=raw.get("locations") or [],
        location_filter=loc_filter,
        include_keywords=raw.get("include_keywords") or [],
        exclude_keywords=raw.get("exclude_keywords") or [],
        target_employers=target_employers,
        greenhouse_board_tokens=gh_tokens,
        lever_board_tokens=lv_tokens,
        ashby_board_names=ab_names,
        linkedin_search_queries=raw.get("linkedin_search_queries") or [],
        linkedin_location=(raw.get("linkedin_location") or "").strip(),
        linkedin_date_posted=(raw.get("linkedin_date_posted") or "r604800").strip(),
        linkedin_sort_by=(raw.get("linkedin_sort_by") or "DD").strip(),
        freshness_max_days=int(raw.get("freshness_max_days") or 5),
        freshness_boost_under_hours=int(raw.get("freshness_boost_under_hours") or 24),
    )
