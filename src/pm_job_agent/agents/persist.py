"""Write pipeline results to a timestamped CSV in the configured output directory.

This is the persist node in the core loop. It always writes a file — even when
ranked_jobs is empty — so every run produces a record on disk.

Column order is optimised for reviewing in a spreadsheet:
  score, score_rationale, flagged, new, title, company, location, url, source,
  source_posted_at, id, description_snippet, resume_note, cover_letter

  ``source_posted_at`` is filled when the job source provides it (e.g. LinkedIn relative
  ``postedAt`` from Apify). It is not the same as ``discovered_date`` in Google Sheets
  (first time this pipeline appended the row).

The `flagged` column is empty after a run. Set it to "yes" for roles you want
to apply to, then run `pm-job-agent generate <this_file>` to generate documents
for those specific rows.

The `new` column is "yes" for jobs not seen in any previous run, empty otherwise.
After writing the CSV, seen_jobs.json is updated with all job IDs from this run.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.services.seen_jobs import add_job_ids, load_seen, save_seen

logger = logging.getLogger(__name__)

_COLUMNS = [
    "score", "score_rationale", "flagged", "new", "title", "company", "location", "url",
    "source", "source_posted_at", "id", "description_snippet", "resume_note", "cover_letter",
]


def persist_jobs(state: CoreLoopState) -> dict:
    """Write ranked_jobs to a CSV and update seen_jobs.json."""
    settings = get_settings()
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"run_{timestamp}.csv"

    ranked = state.get("ranked_jobs") or []
    new_job_ids = set(state.get("new_job_ids") or [])
    _write_csv(output_path, ranked, new_job_ids)

    # Update seen_jobs.json with all job IDs from this run.
    all_ids = [job["id"] for job in ranked if job.get("id")]
    seen = load_seen(settings.seen_jobs_path, ttl_days=settings.seen_jobs_ttl_days)
    updated_seen = add_job_ids(seen, all_ids)
    save_seen(settings.seen_jobs_path, updated_seen)

    logger.info("Wrote %d job(s) to %s (%d new).", len(ranked), output_path, len(new_job_ids))
    return {"output_path": str(output_path)}


def _write_csv(path: Path, ranked_jobs: list, new_job_ids: set) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for job in ranked_jobs:
            row = {col: job.get(col, "") for col in _COLUMNS}
            # flagged empty on write; user sets for roles to generate documents for
            row["flagged"] = ""
            row["new"] = "yes" if job.get("id") in new_job_ids else ""
            row["resume_note"] = ""
            row["cover_letter"] = ""
            writer.writerow(row)
