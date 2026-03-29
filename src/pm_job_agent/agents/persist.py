"""Write pipeline results to a timestamped CSV in the configured output directory.

This is the final node in the core loop. It always writes a file — even when
ranked_jobs is empty — so every run produces a record on disk.

Column order is optimised for reviewing in a spreadsheet:
  score, flagged, title, company, location, url, source, id,
  description_snippet, resume_note, cover_letter

The `flagged` column is empty after a run. Set it to "yes" for roles you want
to apply to, then run `pm-job-agent generate <this_file>` to generate documents
for those specific rows.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState

logger = logging.getLogger(__name__)

_COLUMNS = [
    "score", "flagged", "title", "company", "location", "url", "source", "id",
    "description_snippet", "resume_note", "cover_letter",
]


def persist_jobs(state: CoreLoopState) -> dict:
    """Write ranked_jobs to a CSV. Documents are generated separately on demand."""
    settings = get_settings()
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"run_{timestamp}.csv"

    ranked = state.get("ranked_jobs") or []
    _write_csv(output_path, ranked)

    logger.info("Wrote %d job(s) to %s", len(ranked), output_path)
    return {"output_path": str(output_path)}


def _write_csv(path: Path, ranked_jobs: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for job in ranked_jobs:
            row = {col: job.get(col, "") for col in _COLUMNS}
            # flagged is always empty on initial write; user fills it in for roles they want to pursue
            row["flagged"] = ""
            row["resume_note"] = ""
            row["cover_letter"] = ""
            writer.writerow(row)
