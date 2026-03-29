"""LinkedIn job discovery via the Apify automation-lab/linkedin-jobs-scraper Actor.

Uses LinkedIn's public guest API through Apify — no LinkedIn login or cookies required.
Each call runs the Actor synchronously (blocks until complete, up to 2 minutes).

Actor reference: https://apify.com/automation-lab/linkedin-jobs-scraper
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from pm_job_agent.services.types import JobDict

logger = logging.getLogger(__name__)

_ACTOR_ID = "automation-lab/linkedin-jobs-scraper"
_DEFAULT_MAX_RESULTS = 25
# LinkedIn job URLs: https://www.linkedin.com/jobs/view/1234567890
_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")


class IntegrationError(Exception):
    """Base for all integration-layer failures."""


class LinkedInError(IntegrationError):
    """Raised when the LinkedIn/Apify Actor returns an unexpected result."""


class LinkedInClient:
    """Fetch LinkedIn job listings via the Apify Actor."""

    def __init__(self, api_token: str, max_results: int = _DEFAULT_MAX_RESULTS) -> None:
        self._api_token = api_token
        self._max_results = max_results

    def fetch_jobs(self, search_query: str, title_keywords: list[str]) -> list[JobDict]:
        """Run the LinkedIn scraper Actor and return matched jobs.

        Args:
            search_query: Keyword string sent directly to LinkedIn Jobs search
                          (e.g. "AI Product Manager"). Controls what LinkedIn returns.
            title_keywords: Filter the results locally — keep only jobs whose title
                            contains any of these strings (case-insensitive). If empty,
                            all results are returned.

        Raises:
            LinkedInError: On Actor failure, timeout, or import error.
        """
        try:
            from apify_client import ApifyClient
        except ImportError as exc:
            raise LinkedInError(
                "apify-client is not installed. Run: pip install apify-client"
            ) from exc

        client = ApifyClient(token=self._api_token)
        run_input = {
            "searchKeywords": search_query,
            "maxResults": self._max_results,
        }

        try:
            run = client.actor(_ACTOR_ID).call(
                run_input=run_input,
                timeout=timedelta(seconds=120),
            )
        except Exception as exc:
            raise LinkedInError(
                f"Apify Actor call failed for query '{search_query}': {exc}"
            ) from exc

        if run is None:
            raise LinkedInError(
                f"Apify Actor returned no run object for query '{search_query}'. "
                "Check that your APIFY_API_TOKEN is valid and has sufficient credits."
            )

        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        logger.info(
            "LinkedIn Actor returned %d item(s) for query '%s'", len(items), search_query
        )

        jobs: list[JobDict] = []
        for item in items:
            job = _map_item(item)
            if job is None:
                continue
            if _title_matches(job["title"], title_keywords):
                jobs.append(job)

        logger.info(
            "LinkedIn '%s': %d job(s) after title filtering.", search_query, len(jobs)
        )
        return jobs


def _map_item(item: dict) -> JobDict | None:
    """Map a single Actor output item to JobDict. Returns None if required fields are missing."""
    title = item.get("title") or item.get("jobTitle") or ""
    # Actor may return company as "company" or "companyName"
    company = item.get("company") or item.get("companyName") or ""
    url = item.get("jobUrl") or item.get("url") or ""

    if not title or not url:
        logger.warning("Skipping LinkedIn item missing title or url: %s", item)
        return None

    job_id = _extract_job_id(url)
    if not job_id:
        logger.warning("Could not extract job ID from LinkedIn URL '%s' — skipping.", url)
        return None

    description_raw = item.get("description") or item.get("descriptionText") or ""
    snippet = description_raw[:500]

    return JobDict(
        id=f"linkedin:{job_id}",
        title=title,
        company=company,
        url=url,
        source="linkedin",
        description_snippet=snippet,
        location=item.get("location") or "",
    )


def _extract_job_id(url: str) -> str:
    """Extract the numeric job ID from a LinkedIn job URL."""
    match = _JOB_ID_RE.search(url)
    return match.group(1) if match else ""


def _title_matches(title: str, keywords: list[str]) -> bool:
    """Return True if title contains any keyword, or if keywords list is empty."""
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)
