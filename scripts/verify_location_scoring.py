"""Dry-run location scoring verification.

Reads an existing CSV from a previous pipeline run and re-scores every job
using the current scoring logic + your live search_profile.yaml. No API calls,
no LLM, no writes to the CSV.

Usage:
    .venv/bin/python scripts/verify_location_scoring.py [path/to/run.csv]

Defaults to the most recent CSV in outputs/ if no path is given.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# Allow importing from src/ without installing the package in editable mode.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pm_job_agent.agents.scoring import _score_job  # noqa: E402 (after sys.path fix)
from pm_job_agent.config.search_profile import load_search_profile  # noqa: E402

PROFILE_PATH = Path(__file__).parent.parent / "private" / "search_profile.yaml"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

COL_W = {
    "title": 45,
    "company": 18,
    "location": 30,
    "old": 6,
    "new": 6,
    "flag": 8,
}


def _find_latest_csv() -> Path:
    csvs = sorted(OUTPUTS_DIR.glob("run_*.csv"), reverse=True)
    if not csvs:
        sys.exit(f"No run_*.csv files found in {OUTPUTS_DIR}")
    return csvs[0]


def _fmt(value: str, width: int) -> str:
    value = value[:width] if len(value) > width else value
    return value.ljust(width)


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _find_latest_csv()
    if not csv_path.exists():
        sys.exit(f"CSV not found: {csv_path}")

    profile = load_search_profile(PROFILE_PATH)
    print(f"\nProfile locations: {profile.locations or '(none — no location filter)'}")
    print(f"CSV:               {csv_path.name}\n")

    header = (
        f"{'TITLE':{COL_W['title']}}  "
        f"{'COMPANY':{COL_W['company']}}  "
        f"{'LOCATION':{COL_W['location']}}  "
        f"{'OLD':>{COL_W['old']}}  "
        f"{'NEW':>{COL_W['new']}}  "
        f"{'STATUS':{COL_W['flag']}}"
    )
    print(header)
    print("-" * len(header))

    filtered_count = 0
    kept_count = 0

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            job = {
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "location": row.get("location", ""),
                "description_snippet": row.get("description_snippet", ""),
                "id": row.get("id", ""),
                "url": row.get("url", ""),
                "source": row.get("source", ""),
            }
            old_score = float(row.get("score", 0.0))
            new_score = _score_job(job, profile)

            was_filtered_by_location = (
                profile.locations
                and job["location"]
                and not any(loc.lower() in job["location"].lower() for loc in profile.locations)
            )

            if was_filtered_by_location:
                status = "FILTERED"
                filtered_count += 1
            else:
                status = "OK"
                kept_count += 1

            print(
                f"{_fmt(job['title'], COL_W['title'])}  "
                f"{_fmt(job['company'], COL_W['company'])}  "
                f"{_fmt(job['location'], COL_W['location'])}  "
                f"{old_score:>{COL_W['old']}.1f}  "
                f"{new_score:>{COL_W['new']}.1f}  "
                f"{status}"
            )

    print("-" * len(header))
    print(f"\nSummary: {kept_count} kept, {filtered_count} filtered by location\n")


if __name__ == "__main__":
    main()
