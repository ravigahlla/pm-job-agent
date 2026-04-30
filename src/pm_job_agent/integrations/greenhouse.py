"""Greenhouse Job Board API client.

Queries per-company job boards using the public Greenhouse board API (no auth required for reads).
Each company has a unique board_token — find it at the end of their board URL:
  https://boards.greenhouse.io/<token>/

API reference: https://developer.greenhouse.io/job-board.html
"""

from __future__ import annotations

import httpx

from pm_job_agent.services.types import JobDict

_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class IntegrationError(Exception):
    """Base for all integration-layer failures."""


class GreenhouseError(IntegrationError):
    """Raised when the Greenhouse API returns an unexpected response."""


class GreenhouseClient:
    """Fetch jobs from one or more Greenhouse company boards."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch_jobs(
        self,
        board_token: str,
        title_keywords: list[str],
        *,
        company_label: str | None = None,
    ) -> list[JobDict]:
        """Return jobs from one company board that match any title keyword.

        Args:
            board_token: The company's Greenhouse board slug (e.g. "anthropic").
            title_keywords: Keep only jobs whose title contains any of these (case-insensitive).
                            If empty, all jobs are returned.

        Raises:
            GreenhouseError: On any non-2xx response or network failure.
        """
        url = f"{_BASE_URL}/{board_token}/jobs"
        try:
            response = httpx.get(url, params={"content": "true"}, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise GreenhouseError(
                f"Network error fetching Greenhouse board '{board_token}': {exc}"
            ) from exc

        if response.status_code != 200:
            raise GreenhouseError(
                f"Greenhouse board '{board_token}' returned HTTP {response.status_code}. "
                "Check that the board token exists and is public."
            )

        raw_jobs = response.json().get("jobs") or []
        return [
            _map_job(job, board_token, company_label=company_label)
            for job in raw_jobs
            if _title_matches(job.get("title", ""), title_keywords)
        ]


def _title_matches(title: str, keywords: list[str]) -> bool:
    """Return True if title contains any keyword, or if keywords list is empty."""
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def _map_job(raw: dict, board_token: str, *, company_label: str | None = None) -> JobDict:
    """Map a Greenhouse job object to the internal JobDict schema."""
    location = raw.get("location") or {}
    content = raw.get("content") or ""
    # Greenhouse content is HTML; store a short plain-text snippet for scoring.
    snippet = _strip_html(content)[:500]
    company = company_label if company_label else board_token

    return JobDict(
        id=f"greenhouse:{board_token}:{raw['id']}",
        title=raw.get("title") or "",
        company=company,
        url=raw.get("absolute_url") or "",
        source="greenhouse",
        description_snippet=snippet,
        location=location.get("name") or "",
    )


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string (basic; sufficient for snippet extraction)."""
    import re

    return re.sub(r"<[^>]+>", " ", html).strip()
