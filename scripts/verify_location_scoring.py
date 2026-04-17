"""Dry-run checks for strict location gate and keyword pre-filter.

Reads an existing CSV from a previous pipeline run and, for each row, reports
whether the job would pass ``job_passes_location_gate`` and ``_passes_pre_filter``
under your live ``private/search_profile.yaml``. No API calls and no LLM.

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

from pm_job_agent.agents.scoring import _passes_pre_filter  # noqa: E402
from pm_job_agent.config.search_profile import (  # noqa: E402
    job_passes_location_gate,
    load_search_profile,
)

PROFILE_PATH = Path(__file__).parent.parent / "private" / "search_profile.yaml"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

COL_W = {
    "title": 45,
    "company": 18,
    "location": 30,
    "score": 6,
    "loc_ok": 6,
    "kw_ok": 6,
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
    print(f"\nProfile location_filter: {profile.location_filter}")
    print(f"Profile locations:      {profile.locations or '(none)'}")
    print(f"CSV:                    {csv_path.name}\n")

    header = (
        f"{'TITLE':{COL_W['title']}}  "
        f"{'COMPANY':{COL_W['company']}}  "
        f"{'LOCATION':{COL_W['location']}}  "
        f"{'SCORE':>{COL_W['score']}}  "
        f"{'LOC_OK':>{COL_W['loc_ok']}}  "
        f"{'KW_OK':>{COL_W['kw_ok']}}"
    )
    print(header)
    print("-" * len(header))

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            job = {
                "id": row.get("id", ""),
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "url": row.get("url", ""),
                "source": row.get("source", ""),
                "description_snippet": row.get("description_snippet", ""),
                "location": row.get("location", ""),
            }
            csv_score = float(row.get("score", 0.0) or 0.0)
            loc_ok, _ = job_passes_location_gate(job, profile)
            kw_ok, _ = _passes_pre_filter(job, profile)

            print(
                f"{_fmt(job['title'], COL_W['title'])}  "
                f"{_fmt(job['company'], COL_W['company'])}  "
                f"{_fmt(job.get('location', ''), COL_W['location'])}  "
                f"{csv_score:>{COL_W['score']}.1f}  "
                f"{'yes' if loc_ok else 'no':>{COL_W['loc_ok']}}  "
                f"{'yes' if kw_ok else 'no':>{COL_W['kw_ok']}}"
            )

    print("-" * len(header))
    print(
        "\nLOC_OK = would pass strict location gate (or soft / no locations). "
        "KW_OK = would reach LLM under keyword pre-filter. "
        "SCORE is from the CSV (not recomputed here).\n"
    )


if __name__ == "__main__":
    main()
