"""Sync ranked jobs to the Google Sheets cross-run job tracker.

Appends jobs that are not already in the Sheet (deduplicated by job_id).
The Sheet is the persistent record you use to track status and notes across
all pipeline runs — per-run CSVs remain as raw backup.

Skips silently if GOOGLE_SHEETS_ID is not configured, so local runs without
Sheets set up continue to work normally.

Column layout in the Sheet:
  job_id | title | company | location | url | score | source | discovered_date
  | source_posted_at | new | status | notes | resume_note | cover_letter | score_rationale

  status, notes, resume_note, cover_letter are never overwritten by the pipeline.
"""

from __future__ import annotations

import logging
from typing import Callable

from pm_job_agent.config.settings import Settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.integrations.sheets import SheetsClient, SheetsError

logger = logging.getLogger(__name__)


def sync_to_sheet(state: CoreLoopState, *, settings: Settings) -> dict:
    """LangGraph node: append new jobs to the Google Sheet tracker.

    Skips gracefully if:
    - GOOGLE_SHEETS_ID is not set
    - The service account file does not exist (e.g. local dev without Sheets configured)
    - The Sheets API returns an error (logs a warning but does not fail the pipeline)
    """
    if not settings.google_sheets_id:
        logger.info(
            "GOOGLE_SHEETS_ID is not set — skipping Google Sheets sync. "
            "Add it to .env to enable the cross-run tracker."
        )
        return {}

    if not settings.google_service_account_path.exists():
        logger.warning(
            "GOOGLE_SHEETS_ID is set but service account file not found at '%s' — "
            "skipping Sheets sync. See README 'Google Sheets setup' for instructions.",
            settings.google_service_account_path,
        )
        return {}

    ranked = state.get("ranked_jobs") or []
    if not ranked:
        logger.info("No ranked jobs to sync to Google Sheet.")
        return {}

    new_job_ids = set(state.get("new_job_ids") or [])

    try:
        client = SheetsClient(
            sheet_id=settings.google_sheets_id,
            service_account_path=settings.google_service_account_path,
        )
        existing_ids = client.get_existing_ids()
        appended = client.append_jobs(ranked, new_job_ids=new_job_ids, existing_ids=existing_ids)
        logger.info(
            "Google Sheets sync complete: %d new row(s) appended, %d already present.",
            appended,
            len(ranked) - appended,
        )
    except SheetsError as exc:
        # Log but do not raise — a Sheets failure must not kill the pipeline run.
        logger.warning("Google Sheets sync failed (pipeline continues): %s", exc)

    return {}


def make_sync_sheets_node(settings: Settings) -> Callable[[CoreLoopState], dict]:
    """Return a LangGraph-compatible node function with settings bound."""
    def _node(state: CoreLoopState) -> dict:
        return sync_to_sheet(state, settings=settings)
    return _node
