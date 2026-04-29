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

When ``location_filter`` is ``strict`` in the search profile and ``locations`` is
non-empty, jobs whose non-empty ``location`` does not contain any profile substring
are dropped after deduplication (blank location still passes).
"""

from __future__ import annotations

import logging

from pm_job_agent.config.search_profile import job_passes_location_gate, load_search_profile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.integrations.greenhouse import GreenhouseClient, GreenhouseError
from pm_job_agent.integrations.lever import LeverClient, LeverError
from pm_job_agent.integrations.linkedin import LinkedInClient, LinkedInError
from pm_job_agent.services.freshness import resolve_freshness
from pm_job_agent.services.seen_jobs import load_seen
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
                fetched = li_client.fetch_jobs(query, profile.target_titles, profile)
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

    # Strict location gate (substring match); blank job.location always passes.
    location_kept: list[JobDict] = []
    for job in deduped:
        ok, reason = job_passes_location_gate(job, profile)
        if ok:
            location_kept.append(job)
        else:
            logger.debug("%s — job %s", reason, job.get("id"))
    dropped_loc = len(deduped) - len(location_kept)
    if dropped_loc:
        logger.info("Removed %d job(s) by strict location filter.", dropped_loc)

    # Freshness gate: keep <= freshness_max_days, using first-seen fallback when source
    # does not provide posted age.
    seen_map = load_seen(settings.seen_jobs_path, ttl_days=settings.seen_jobs_ttl_days)
    max_age_hours = float(profile.freshness_max_days * 24)
    freshness_kept: list[JobDict] = []
    for job in location_kept:
        age_hours, basis = resolve_freshness(job, seen_map)
        enriched = {**job, "freshness_age_hours": age_hours, "freshness_basis": basis}
        if age_hours <= max_age_hours:
            freshness_kept.append(enriched)
        else:
            logger.debug(
                "Excluded by freshness gate (> %s days): %s age=%.1fh basis=%s",
                profile.freshness_max_days,
                job.get("id"),
                age_hours,
                basis,
            )
    dropped_fresh = len(location_kept) - len(freshness_kept)
    if dropped_fresh:
        logger.info(
            "Removed %d job(s) older than %d day(s).",
            dropped_fresh,
            profile.freshness_max_days,
        )

    return {"jobs": freshness_kept}
