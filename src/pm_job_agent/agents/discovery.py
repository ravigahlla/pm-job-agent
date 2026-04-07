"""Job discovery from external sources.

Flow: load SearchProfile → query each configured source → deduplicate → return jobs.

Sources:
  - Greenhouse: queried if greenhouse_board_tokens is non-empty (no API key required)
  - Lever:      queried if lever_board_tokens is non-empty (no API key required)
  - LinkedIn:   queried if linkedin_search_queries is non-empty AND APIFY_API_TOKEN is set

Two deduplication passes run within each pipeline execution:
  1. By job_id — prevents the same ID appearing twice across sources/queries.
  2. By (company, title) — prevents large platforms (Meta, Google) from returning
     the same posting under different IDs across multiple LinkedIn search queries,
     and collapses roles that appear on both Greenhouse and Lever.

If a source is unconfigured or fails, it is skipped — the run continues with whatever
jobs other sources returned.
"""

from __future__ import annotations

import logging

from pm_job_agent.config.search_profile import load_search_profile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.integrations.greenhouse import GreenhouseClient, GreenhouseError
from pm_job_agent.integrations.lever import LeverClient, LeverError
from pm_job_agent.integrations.linkedin import LinkedInClient, LinkedInError
from pm_job_agent.services.types import JobDict

logger = logging.getLogger(__name__)


def discover_jobs(_: CoreLoopState) -> dict:
    """Query all configured job sources and return deduplicated JobDicts."""
    settings = get_settings()
    profile = load_search_profile(settings.search_profile_path)

    seen: dict[str, bool] = {}
    jobs: list[JobDict] = []

    # --- Greenhouse ---
    if not profile.greenhouse_board_tokens:
        logger.info(
            "No greenhouse_board_tokens configured in %s — skipping Greenhouse.",
            settings.search_profile_path,
        )
    else:
        gh_client = GreenhouseClient()
        for token in profile.greenhouse_board_tokens:
            try:
                fetched = gh_client.fetch_jobs(token, profile.target_titles)
                for job in fetched:
                    if job["id"] not in seen:
                        seen[job["id"]] = True
                        jobs.append(job)
                logger.info("Greenhouse '%s': %d matching jobs.", token, len(fetched))
            except GreenhouseError as exc:
                # Log and continue — one bad board should not kill the whole run.
                logger.warning("Greenhouse board '%s' failed: %s", token, exc)

    # --- LinkedIn (via Apify) ---
    if not profile.linkedin_search_queries:
        logger.info(
            "No linkedin_search_queries configured in %s — skipping LinkedIn.",
            settings.search_profile_path,
        )
    elif not settings.apify_api_token:
        logger.info(
            "APIFY_API_TOKEN is not set — skipping LinkedIn. "
            "Add it to .env to enable LinkedIn discovery."
        )
    else:
        li_client = LinkedInClient(
            api_token=settings.apify_api_token.get_secret_value()
        )
        for query in profile.linkedin_search_queries:
            try:
                fetched = li_client.fetch_jobs(query, profile.target_titles)
                for job in fetched:
                    if job["id"] not in seen:
                        seen[job["id"]] = True
                        jobs.append(job)
            except LinkedInError as exc:
                # Log and continue — one bad query should not kill the whole run.
                logger.warning("LinkedIn query '%s' failed: %s", query, exc)

    # --- Lever ---
    if not profile.lever_board_tokens:
        logger.info(
            "No lever_board_tokens configured in %s — skipping Lever.",
            settings.search_profile_path,
        )
    else:
        lv_client = LeverClient()
        for token in profile.lever_board_tokens:
            try:
                fetched = lv_client.fetch_jobs(token, profile.target_titles)
                for job in fetched:
                    if job["id"] not in seen:
                        seen[job["id"]] = True
                        jobs.append(job)
                logger.info("Lever '%s': %d matching jobs.", token, len(fetched))
            except LeverError as exc:
                # Log and continue — one bad board should not kill the whole run.
                logger.warning("Lever board '%s' failed: %s", token, exc)

    # Second dedup pass: drop jobs with the same (company, title) pair.
    # Large platforms (Meta, Google) return the same listing under different IDs
    # across multiple LinkedIn queries; this also collapses roles that appear on
    # both Greenhouse and Lever boards.
    seen_company_title: set[tuple[str, str]] = set()
    deduped: list[JobDict] = []
    for job in jobs:
        key = (job.get("company", "").lower().strip(), job.get("title", "").lower().strip())
        if key not in seen_company_title:
            seen_company_title.add(key)
            deduped.append(job)

    removed = len(jobs) - len(deduped)
    if removed:
        logger.info("Removed %d duplicate job(s) by (company, title).", removed)

    return {"jobs": deduped}
