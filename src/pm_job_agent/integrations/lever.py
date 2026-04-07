"""Lever Job Board API client.

Queries per-company job boards using the public Lever posting API (no auth required).
Each company has a board slug — find it at the end of their Lever board URL:
  https://jobs.lever.co/<slug>/

API reference: https://hire.lever.co/developer/postings
"""

from __future__ import annotations

import logging
import re

import httpx

from pm_job_agent.services.types import JobDict

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.lever.co/v0/postings"


class IntegrationError(Exception):
    """Base for all integration-layer failures."""


class LeverError(IntegrationError):
    """Raised when the Lever API returns an unexpected response."""


class LeverClient:
    """Fetch jobs from one or more Lever company boards."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch_jobs(self, board_token: str, title_keywords: list[str]) -> list[JobDict]:
        """Return jobs from one company board that match any title keyword.

        Args:
            board_token: The company's Lever board slug (e.g. "notion").
            title_keywords: Keep only jobs whose title contains any of these (case-insensitive).
                            If empty, all jobs are returned.

        Raises:
            LeverError: On non-2xx responses other than 404, or network failure.
                        404 is logged as a warning and returns an empty list so
                        stale board tokens don't pollute run logs with errors.
        """
        url = f"{_BASE_URL}/{board_token}"
        try:
            response = httpx.get(url, params={"mode": "json"}, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise LeverError(
                f"Network error fetching Lever board '{board_token}': {exc}"
            ) from exc

        if response.status_code == 404:
            logger.warning(
                "Lever board '%s' not found (404) — skipping. "
                "Remove this token from search_profile.yaml if the board no longer exists.",
                board_token,
            )
            return []

        if response.status_code != 200:
            raise LeverError(
                f"Lever board '{board_token}' returned HTTP {response.status_code}. "
                "Check that the board slug exists and is public."
            )

        raw_jobs = response.json()
        if not isinstance(raw_jobs, list):
            raise LeverError(
                f"Lever board '{board_token}' returned unexpected response shape."
            )

        return [
            _map_job(job, board_token)
            for job in raw_jobs
            if _title_matches(job.get("text", ""), title_keywords)
        ]


def _title_matches(title: str, keywords: list[str]) -> bool:
    """Return True if title contains any keyword, or if keywords list is empty."""
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def _map_job(raw: dict, board_token: str) -> JobDict:
    """Map a Lever posting object to the internal JobDict schema."""
    categories = raw.get("categories") or {}
    description_html = raw.get("description") or raw.get("descriptionPlain") or ""
    snippet = _strip_html(description_html)[:500]

    # Lever company name is sometimes in the posting; fall back to the board slug.
    company = raw.get("company") or board_token

    return JobDict(
        id=f"lever:{board_token}:{raw['id']}",
        title=raw.get("text") or "",
        company=company,
        url=raw.get("hostedUrl") or raw.get("applyUrl") or "",
        source="lever",
        description_snippet=snippet,
        location=categories.get("location") or categories.get("allLocations", [""])[0] if isinstance(categories.get("allLocations"), list) else "",
    )


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string (basic; sufficient for snippet extraction)."""
    return re.sub(r"<[^>]+>", " ", html).strip()
