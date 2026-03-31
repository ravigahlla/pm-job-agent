#!/usr/bin/env python3
"""One-time script to re-score all jobs in the Google Sheet with the v2 LLM scorer.

Usage:
    # Dry run (default) — prints a preview table, writes nothing to the Sheet
    python scripts/rescore_sheet.py

    # Live run — updates score and score_rationale columns in the Sheet
    python scripts/rescore_sheet.py --write

    # Use Ollama locally (no API cost)
    python scripts/rescore_sheet.py --write --provider ollama

What it does:
  1. Reads all rows from your Google Sheet tracker.
  2. Scans all outputs/run_*.csv files and builds a job_id → description_snippet
     lookup. Jobs with a matching CSV entry get a full description in the scoring
     prompt; those without are scored on title + company + location only.
  3. Re-scores every job using the same _score_single() function the pipeline uses,
     against your current agent-context.md.
  4. In dry-run mode: prints a before/after table. With --write: batch-updates the
     `score` column in place and adds a `score_rationale` column if it doesn't exist.

What is NEVER changed:
  status, notes, resume_note, cover_letter — every cell you've edited is preserved.

Prerequisites:
  - GOOGLE_SHEETS_ID and GOOGLE_SERVICE_ACCOUNT_PATH must be set (or default to
    private/service_account.json).
  - AGENT_CONTEXT_PATH must point to your private/agent-context.md.
  - DEFAULT_LLM_PROVIDER (or --provider flag) must be configured.

Quota note:
  The Sheet is read once and written once (batch update). LLM calls are one per job.
  At 280 jobs and ~0.3s per call, expect ~90s of LLM time plus a few seconds for
  the Sheet read/write.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Resolve project root so this script runs from any working directory.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# Load .env before importing settings.
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Description lookup — built from local run CSVs
# ---------------------------------------------------------------------------

def _build_description_lookup(outputs_dir: Path) -> dict[str, str]:
    """Scan all run_*.csv files and return {job_id: description_snippet}.

    Later CSVs overwrite earlier ones for the same job_id (the most recent
    description wins, though in practice they don't change between runs).
    """
    lookup: dict[str, str] = {}
    csv_files = sorted(outputs_dir.glob("run_*.csv"))
    for path in csv_files:
        try:
            with path.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    job_id = row.get("id") or row.get("job_id", "")
                    snippet = row.get("description_snippet", "")
                    if job_id and snippet:
                        lookup[job_id] = snippet
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read %s: %s", path.name, exc)
    return lookup


# ---------------------------------------------------------------------------
# Sheet helpers — extends SheetsClient for this script's needs
# ---------------------------------------------------------------------------

def _get_sheet_client(settings):
    """Connect to the Google Sheet; raise with a clear message on failure."""
    from pm_job_agent.integrations.sheets import SheetsClient, SheetsError

    if not settings.google_sheets_id:
        print(
            "Error: GOOGLE_SHEETS_ID is not set. Add it to .env and try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.google_service_account_path.exists():
        print(
            f"Error: service account file not found at "
            f"{settings.google_service_account_path}. "
            "See README 'Google Sheets setup' for instructions.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        return SheetsClient(
            sheet_id=settings.google_sheets_id,
            service_account_path=settings.google_service_account_path,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: could not connect to Google Sheet: {exc}", file=sys.stderr)
        sys.exit(1)


def _read_sheet_rows(client) -> tuple[list[str], list[dict]]:
    """Return (header_row, data_rows) from the Sheet.

    data_rows is a list of dicts keyed by header values, with an extra
    '__row_num__' key (1-indexed, 1 = header) for batch update targeting.
    """
    try:
        all_values = client._sheet.get_all_values()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: failed to read Sheet: {exc}", file=sys.stderr)
        sys.exit(1)

    if not all_values:
        return [], []

    header = all_values[0]
    rows = []
    for row_idx, values in enumerate(all_values[1:], start=2):
        # Pad short rows to header length so dict keys always exist.
        padded = values + [""] * (len(header) - len(values))
        row_dict = dict(zip(header, padded))
        row_dict["__row_num__"] = row_idx
        rows.append(row_dict)
    return header, rows


def _ensure_rationale_column(client, header: list[str]) -> int:
    """Ensure score_rationale column exists in the Sheet header.

    Appends the column header to the right of existing columns if missing.
    Returns the 1-indexed column number for score_rationale.
    """
    if "score_rationale" in header:
        return header.index("score_rationale") + 1  # 1-indexed

    # Add header label at the next empty column.
    new_col_idx = len(header) + 1  # 1-indexed
    try:
        import gspread
        col_letter = gspread.utils.rowcol_to_a1(1, new_col_idx)[:-1]
        client._sheet.update(values=[["score_rationale"]], range_name=f"{col_letter}1")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not add score_rationale header: {exc}", file=sys.stderr)
        return -1  # caller will skip rationale writes
    return new_col_idx


def _batch_write_scores(
    client,
    updates: list[tuple[int, float, str]],
    score_col_idx: int,
    rationale_col_idx: int,
) -> None:
    """Write all score and rationale updates in a single batchUpdate API call.

    updates: list of (row_num, score, rationale) — row_num is 1-indexed Sheet row.
    score_col_idx, rationale_col_idx: 1-indexed column positions.
    """
    import gspread

    cell_updates = []
    for row_num, score, rationale in updates:
        score_a1 = gspread.utils.rowcol_to_a1(row_num, score_col_idx)
        cell_updates.append({"range": score_a1, "values": [[round(score, 4)]]})
        if rationale_col_idx > 0:
            rat_a1 = gspread.utils.rowcol_to_a1(row_num, rationale_col_idx)
            cell_updates.append({"range": rat_a1, "values": [[rationale]]})

    if not cell_updates:
        return

    try:
        client._sheet.spreadsheet.values_batch_update(
            {"valueInputOption": "RAW", "data": cell_updates}
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: batch write failed: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _build_job_dict(row: dict, description_lookup: dict[str, str]) -> dict:
    """Convert a Sheet row to a minimal JobDict for the scorer."""
    job_id = row.get("job_id", "")
    return {
        "id": job_id,
        "title": row.get("title", ""),
        "company": row.get("company", ""),
        "location": row.get("location", ""),
        "url": row.get("url", ""),
        "source": row.get("source", ""),
        "description_snippet": description_lookup.get(job_id, ""),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _print_preview_table(
    rows: list[dict],
    new_scores: list[tuple[float, str]],
) -> None:
    sep = "-" * 110
    print(sep)
    print(f"{'#':<4} {'Title':<35} {'Company':<18} {'Old':>5} {'New':>6} {'Delta':>6}  Rationale (truncated)")
    print(sep)
    for i, (row, (new_score, rationale)) in enumerate(zip(rows, new_scores), 1):
        old_str = row.get("score", "")
        try:
            old_val = float(old_str)
            delta = new_score - old_val
            delta_str = f"{delta:+.2f}"
            flag = " !" if abs(delta) > 0.30 else "  "
        except (ValueError, TypeError):
            old_str = "n/a"
            delta_str = "n/a"
            flag = "  "

        title = (row.get("title") or "")[:34]
        company = (row.get("company") or "")[:17]
        rat_short = (rationale or "")[:40]
        print(f"{i:<4} {title:<35} {company:<18} {old_str:>5} {new_score:>6.2f} {delta_str:>6}{flag}  {rat_short}")
    print(sep)


def _print_summary(rows: list[dict], new_scores: list[tuple[float, str]], no_desc_count: int) -> None:
    pairs = []
    for row, (new_score, _) in zip(rows, new_scores):
        try:
            old = float(row.get("score", ""))
            pairs.append((old, new_score))
        except (ValueError, TypeError):
            pass

    if pairs:
        deltas = [abs(n - o) for o, n in pairs]
        mae = sum(deltas) / len(deltas)
        large = sum(1 for d in deltas if d > 0.30)
        avg_old = sum(o for o, _ in pairs) / len(pairs)
        avg_new = sum(n for _, n in pairs) / len(pairs)
        print(f"\nSummary ({len(pairs)} jobs re-scored):")
        print(f"  Average score before : {avg_old:.3f}")
        print(f"  Average score after  : {avg_new:.3f}")
        print(f"  Mean absolute change : {mae:.3f}")
        print(f"  Large changes (>0.30): {large}")

    if no_desc_count:
        print(
            f"\nNote: {no_desc_count} job(s) had no description in local CSVs and were "
            "scored on title + company + location only."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-score all Google Sheet jobs with the v2 LLM scorer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run without --write first to preview changes.\n"
            "Use --provider ollama for local testing without API costs."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write updated scores to the Sheet. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--provider",
        metavar="PROVIDER",
        help="Override LLM provider: stub | anthropic | openai | gemini | ollama. "
             "Defaults to DEFAULT_LLM_PROVIDER in .env.",
    )
    parser.add_argument(
        "--outputs-dir",
        metavar="DIR",
        default=str(_ROOT / "outputs"),
        help="Directory containing run_*.csv files (default: outputs/).",
    )
    args = parser.parse_args()

    from pm_job_agent.config.settings import get_settings
    from pm_job_agent.config.search_profile import load_search_profile
    from pm_job_agent.agents.scoring import _score_single, _build_scoring_system
    from pm_job_agent.models.llm import get_llm_client, get_llm_client_for_provider

    settings = get_settings()

    # LLM client
    if args.provider:
        llm = get_llm_client_for_provider(args.provider)
        provider_name = args.provider
    else:
        llm = get_llm_client()
        provider_name = settings.default_llm_provider or "stub"
    print(f"LLM provider : {provider_name}")

    # Agent context
    context_path = settings.agent_context_path
    if not context_path.exists():
        print(f"Warning: agent context not found at {context_path}. Scoring without background.")
        context_text = ""
    else:
        context_text = context_path.read_text(encoding="utf-8")
    context_excerpt = context_text[:2000]

    # Scoring criteria (optional; same file used by the live pipeline)
    criteria_path = settings.scoring_criteria_path
    if criteria_path and criteria_path.exists():
        criteria_text = criteria_path.read_text(encoding="utf-8")
        print(f"Criteria     : loaded from {criteria_path} ({len(criteria_text)} chars)")
    else:
        criteria_text = ""
        print(f"Criteria     : none (set SCORING_CRITERIA_PATH in .env to enable)")
    scoring_system = _build_scoring_system(criteria_text)

    # Search profile (for keyword pre-filter)
    profile = load_search_profile(settings.search_profile_path)

    # Description lookup from local CSVs
    outputs_dir = Path(args.outputs_dir)
    description_lookup = _build_description_lookup(outputs_dir)
    print(f"Descriptions : {len(description_lookup)} loaded from {outputs_dir.name}/run_*.csv")

    # Connect to Sheet and read all rows
    client = _get_sheet_client(settings)
    print("Reading Sheet...", end=" ", flush=True)
    header, rows = _read_sheet_rows(client)
    if not rows:
        print("\nSheet is empty — nothing to re-score.")
        return
    print(f"{len(rows)} rows found.")

    score_col_idx = (header.index("score") + 1) if "score" in header else -1
    if score_col_idx < 0:
        print("Error: Sheet has no 'score' column — is this the right sheet?", file=sys.stderr)
        sys.exit(1)

    # Score every job
    print(f"\nScoring {len(rows)} jobs", end="", flush=True)
    new_scores: list[tuple[float, str]] = []
    no_desc_count = 0
    t_start = time.time()

    for i, row in enumerate(rows, 1):
        job = _build_job_dict(row, description_lookup)
        if not job["description_snippet"]:
            no_desc_count += 1
        result = _score_single(job, profile, llm, context_excerpt, scoring_system=scoring_system)
        new_scores.append((result["score"], result.get("score_rationale", "")))
        if i % 20 == 0:
            elapsed = time.time() - t_start
            print(f"\n  {i}/{len(rows)} scored ({elapsed:.0f}s elapsed)", end="", flush=True)

    elapsed_total = time.time() - t_start
    print(f"\n  Done — {len(rows)} jobs scored in {elapsed_total:.0f}s.\n")

    # Preview table (always shown)
    _print_preview_table(rows, new_scores)
    _print_summary(rows, new_scores, no_desc_count)

    if not args.write:
        print(
            "\nDry run complete — no changes written to the Sheet.\n"
            "Re-run with --write to apply the updates."
        )
        return

    # Write back to Sheet
    print("\nWriting to Sheet...", end=" ", flush=True)
    rationale_col_idx = _ensure_rationale_column(client, header)

    updates = [
        (row["__row_num__"], score, rationale)
        for row, (score, rationale) in zip(rows, new_scores)
    ]
    _batch_write_scores(client, updates, score_col_idx, rationale_col_idx)
    print(f"done. Updated {len(updates)} rows.")

    if rationale_col_idx > 0:
        print(f"score_rationale column is at column {rationale_col_idx}.")
    else:
        print("Warning: score_rationale column could not be added — check Sheet permissions.")


if __name__ == "__main__":
    main()
