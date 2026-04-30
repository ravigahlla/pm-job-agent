"""Ashby public job posting API client.

Each organization has a job board name in the URL path:
  https://jobs.ashbyhq.com/<JOB_BOARD_NAME>/

API reference: https://developers.ashbyhq.com/docs/public-job-posting-api
"""

from __future__ import annotations

import logging

import httpx

from pm_job_agent.services.types import JobDict

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class IntegrationError(Exception):
    """Base for all integration-layer failures."""


class AshbyError(IntegrationError):
    """Raised when the Ashby posting API returns an unexpected response."""


class AshbyClient:
    """Fetch jobs from one or more Ashby-hosted job boards."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch_jobs(
        self,
        board_name: str,
        title_keywords: list[str],
        *,
        company_label: str | None = None,
    ) -> list[JobDict]:
        """Return jobs from one board that match any title keyword.

        Args:
            board_name: The Ashby jobs page name (path segment after jobs.ashbyhq.com/).
            title_keywords: Keep only jobs whose title contains any of these (case-insensitive).
                            If empty, all jobs are returned.

        Raises:
            AshbyError: On non-2xx responses other than 404, or network failure.
                        404 is logged as a warning and returns an empty list.
        """
        url = f"{_BASE_URL}/{board_name}"
        try:
            response = httpx.get(url, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise AshbyError(
                f"Network error fetching Ashby board '{board_name}': {exc}"
            ) from exc

        if response.status_code == 404:
            logger.warning(
                "Ashby board '%s' not found (404) — skipping. "
                "Remove this name from search_profile.yaml if the board no longer exists.",
                board_name,
            )
            return []

        if response.status_code != 200:
            raise AshbyError(
                f"Ashby board '{board_name}' returned HTTP {response.status_code}. "
                "Check that the job board name exists and is public."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise AshbyError(f"Ashby board '{board_name}' returned invalid JSON.") from exc

        raw_jobs = body.get("jobs")
        if raw_jobs is None:
            raw_jobs = []
        if not isinstance(raw_jobs, list):
            raise AshbyError(
                f"Ashby board '{board_name}' returned unexpected response shape."
            )

        return [
            _map_job(job, board_name, company_label=company_label)
            for job in raw_jobs
            if isinstance(job, dict) and _title_matches(job.get("title", ""), title_keywords)
        ]


def _title_matches(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def _map_job(raw: dict, board_name: str, *, company_label: str | None = None) -> JobDict:
    """Map an Ashby job object to the internal JobDict schema."""
    snippet = ((raw.get("descriptionPlain") or "") or "").strip()[:500]
    published = raw.get("publishedAt")
    posted_str = str(published).strip() if published is not None else ""
    company = company_label if company_label else board_name

    return JobDict(
        id=f"ashby:{board_name}:{raw['id']}",
        title=(raw.get("title") or "").strip(),
        company=company,
        url=(raw.get("jobUrl") or raw.get("applyUrl") or "").strip(),
        source="ashby",
        description_snippet=snippet,
        location=(raw.get("location") or "").strip(),
        source_posted_at=posted_str,
    )
