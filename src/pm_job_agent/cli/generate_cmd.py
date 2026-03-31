"""On-demand document generation from a reviewed run CSV.

Workflow:
  1. Run `pm-job-agent run` — produces outputs/run_YYYYMMDD_HHMMSS.csv
  2. Open the CSV, set `flagged = yes` for roles you want to apply to
  3. Run `pm-job-agent generate outputs/run_YYYYMMDD_HHMMSS.csv`
     → reads flagged rows, calls LLM for each, writes resume_note + cover_letter
        back into the same file

Only flagged rows are touched; all other rows are preserved as-is.
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path
from typing import Optional

from pm_job_agent.agents.generation import generate_for_jobs
from pm_job_agent.agents.persist import _COLUMNS
from pm_job_agent.config.settings import get_settings
from pm_job_agent.models.llm import LLMClient, get_llm_client

logger = logging.getLogger(__name__)


def _load_agent_context(path: Path) -> str:
    """Read agent context file; return empty string if missing."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Agent context file not found at %s — generating without background context", path)
        return ""


def _reconstruct_job(row: dict) -> dict:
    """Convert a CSV row back into a job dict suitable for generation prompts."""
    return {
        "id": row["id"],
        "title": row["title"],
        "company": row["company"],
        "location": row.get("location", ""),
        "url": row.get("url", ""),
        "source": row.get("source", ""),
        "description_snippet": row.get("description_snippet", ""),
        # Score stored as string in CSV; cast back to float for any downstream use
        "score": float(row["score"]) if row.get("score") else 0.0,
    }


def run_generate(csv_path: Path, llm: Optional[LLMClient] = None) -> None:
    """Read a run CSV, generate documents for flagged rows, update the file in-place.

    `llm` can be passed directly (e.g. from --provider CLI flag) to override the
    provider configured in .env. When None, falls back to DEFAULT_LLM_PROVIDER.
    """
    if not csv_path.exists():
        print(f"Error: file not found — {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Read all rows first so we can write the full file back
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    flagged_rows = [r for r in rows if r.get("flagged", "").strip().lower() == "yes"]

    if not flagged_rows:
        print("No flagged rows found. Set 'flagged' to 'yes' for the roles you want to apply to.")
        return

    print(f"Generating documents for {len(flagged_rows)} flagged role(s)...")

    settings = get_settings()
    context = _load_agent_context(settings.agent_context_path)
    llm = llm or get_llm_client()

    jobs = [_reconstruct_job(r) for r in flagged_rows]
    documents = generate_for_jobs(jobs, context, llm)
    doc_by_id = {d["job_id"]: d for d in documents}

    # Merge generated content back into the full row list
    for row in rows:
        doc = doc_by_id.get(row["id"])
        if doc:
            row["resume_note"] = doc["resume_note"]
            row["cover_letter"] = doc["cover_letter"]

    # Write all rows back — same file, same column order
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Updated {len(documents)} row(s) in {csv_path}")
    for doc in documents:
        job_row = next((r for r in rows if r["id"] == doc["job_id"]), {})
        title = job_row.get("title", doc["job_id"])
        company = job_row.get("company", "")
        print(f"  - {title} @ {company}")
