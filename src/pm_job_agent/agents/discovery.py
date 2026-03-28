"""Job discovery from external sources.

Flow: load SearchProfile → query each configured Greenhouse board → deduplicate → return jobs.
If no board tokens are configured (or the profile file is missing), returns an empty list
without raising — the rest of the pipeline continues normally.
"""

from __future__ import annotations

import logging

from pm_job_agent.config.search_profile import load_search_profile
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.integrations.greenhouse import GreenhouseClient, GreenhouseError
from pm_job_agent.services.types import JobDict

logger = logging.getLogger(__name__)


def discover_jobs(_: CoreLoopState) -> dict:
    """Query all configured job sources and return deduplicated JobDicts."""
    settings = get_settings()
    profile = load_search_profile(settings.search_profile_path)

    if not profile.greenhouse_board_tokens:
        logger.info(
            "No greenhouse_board_tokens configured in %s — skipping Greenhouse.",
            settings.search_profile_path,
        )
        return {"jobs": []}

    client = GreenhouseClient()
    seen: dict[str, bool] = {}
    jobs: list[JobDict] = []

    for token in profile.greenhouse_board_tokens:
        try:
            fetched = client.fetch_jobs(token, profile.target_titles)
            for job in fetched:
                if job["id"] not in seen:
                    seen[job["id"]] = True
                    jobs.append(job)
            logger.info("Greenhouse '%s': %d matching jobs.", token, len(fetched))
        except GreenhouseError as exc:
            # Log and continue — one bad board should not kill the whole run.
            logger.warning("Greenhouse board '%s' failed: %s", token, exc)

    return {"jobs": jobs}
