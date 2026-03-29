"""Identify which jobs in this run are new vs already seen in a previous run.

Loads private/seen_jobs.json (created automatically on first run), evicts
entries older than the configured TTL, and determines which job IDs from
this run have not been seen before. The result is stored in state as
`new_job_ids` and used by both `persist` (to write the `new` CSV column)
and `notify` (to filter the email digest to genuinely new roles).

seen_jobs.json is updated by `persist` after the CSV is written, so this
node is read-only with respect to the file.
"""

from __future__ import annotations

import logging

from pm_job_agent.config.settings import Settings, get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.services.seen_jobs import find_new_ids, load_seen

logger = logging.getLogger(__name__)


def deduplicate_jobs(state: CoreLoopState, *, settings: Settings) -> dict:
    """Compute new_job_ids and store in state."""
    ranked = state.get("ranked_jobs") or []
    all_ids = [job["id"] for job in ranked if job.get("id")]

    seen = load_seen(settings.seen_jobs_path, ttl_days=settings.seen_jobs_ttl_days)
    new_ids = find_new_ids(seen, all_ids)

    logger.info(
        "Deduplication: %d jobs this run, %d new, %d already seen.",
        len(all_ids),
        len(new_ids),
        len(all_ids) - len(new_ids),
    )
    return {"new_job_ids": new_ids}


def make_deduplicate_node(settings: Settings):
    def _node(state: CoreLoopState) -> dict:
        return deduplicate_jobs(state, settings=settings)

    return _node
