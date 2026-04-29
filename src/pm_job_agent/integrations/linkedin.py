"""LinkedIn job discovery via the Apify automation-lab/linkedin-jobs-scraper Actor.

Uses LinkedIn's public guest API through Apify — no LinkedIn login or cookies required.
Each call runs the Actor synchronously (blocks until complete, up to 2 minutes).

Actor reference: https://apify.com/automation-lab/linkedin-jobs-scraper
"""

from __future__ import annotations

import logging
import re

from pm_job_agent.config.search_profile import SearchProfile
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

    def fetch_jobs(
        self,
        search_query: str,
        title_keywords: list[str],
        profile: SearchProfile | None = None,
    ) -> list[JobDict]:
        """Run the LinkedIn scraper Actor and return matched jobs.

        Args:
            search_query: Keyword string sent directly to LinkedIn Jobs search
                          (e.g. "AI Product Manager"). Controls what LinkedIn returns.
            title_keywords: Filter the results locally — keep only jobs whose title
                            contains any of these strings (case-insensitive). If empty,
                            all results are returned.
            profile: Optional search profile for Apify ``location``, ``datePosted``,
                     and ``sortBy`` (see automation-lab/linkedin-jobs-scraper).

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
        run_input: dict = {
            "searchQuery": search_query,
            "maxResults": self._max_results,
        }
        if profile is not None:
            if profile.linkedin_location:
                run_input["location"] = profile.linkedin_location
            dp = (profile.linkedin_date_posted or "all").strip().lower()
            if dp and dp != "all":
                run_input["datePosted"] = profile.linkedin_date_posted.strip()
            sb = (profile.linkedin_sort_by or "").strip()
            if sb:
                run_input["sortBy"] = sb

        try:
            run = client.actor(_ACTOR_ID).call(
                run_input=run_input,
                wait_secs=120,
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
    # Actor returns company as "companyName"; fall back to "company" for other Actor versions
    company = item.get("companyName") or item.get("company") or ""
    # Actor returns "url"; "jobUrl" kept as fallback for other Actor versions
    url = item.get("url") or item.get("jobUrl") or ""

    if not title or not url:
        logger.warning("Skipping LinkedIn item missing title or url: %s", item)
        return None

    # Prefer the top-level numeric "id" field the Actor provides directly;
    # fall back to extracting from URL for resilience against schema changes
    raw_id = str(item["id"]) if item.get("id") else _extract_job_id(url)
    if not raw_id:
        logger.warning("Could not determine job ID for LinkedIn URL '%s' — skipping.", url)
        return None

    # Actor returns plain text in "descriptionText"; "description" kept as fallback
    description_raw = item.get("descriptionText") or item.get("description") or ""
    snippet = description_raw[:500]

    posted = item.get("postedAt") or item.get("posted_at") or ""
    scraped = item.get("scrapedAt") or item.get("scraped_at") or ""

    return JobDict(
        id=f"linkedin:{raw_id}",
        title=title,
        company=company,
        url=url,
        source="linkedin",
        description_snippet=snippet,
        location=item.get("location") or "",
        source_posted_at=str(posted) if posted else "",
        source_scraped_at=str(scraped) if scraped else "",
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
