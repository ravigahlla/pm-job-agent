#!/usr/bin/env python3
"""Eval script for scoring-v2 quality validation.

Usage:
    python scripts/eval_scoring.py outputs/run_YYYYMMDD_HHMMSS.csv

What it does:
  1. Reads a CSV produced by a previous run (must contain a `score` column — works
     with both v1 keyword-score CSVs and v2 LLM-score CSVs).
  2. Samples N jobs: the top-scoring half and a random selection from the rest,
     so we cover both "confident" and "uncertain" score regions.
  3. Calls an oracle LLM (typically a stronger model than the scoring model) to
     independently score each sampled job against agent-context.md.
  4. Prints a comparison table: v1/v2 score vs oracle score, the delta, and both
     rationales side-by-side.
  5. Reports summary statistics: mean absolute error, Spearman rank correlation,
     and a count of large disagreements (delta > 0.3).

Prerequisites:
  - DEFAULT_LLM_PROVIDER (or SCORING_LLM_PROVIDER) and the corresponding API key
    must be set in .env.  The oracle uses DEFAULT_LLM_PROVIDER.
  - AGENT_CONTEXT_PATH must point to your private/agent-context.md.

This script is intentionally standalone and does not import the main pipeline graph
so it can be run on any CSV without triggering a full run.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Optional

# Resolve project root so this script can be run from any directory.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# Load .env before importing settings.
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass  # dotenv not installed; rely on env vars already set


_CONTEXT_MAX_CHARS = 2000

_ORACLE_SYSTEM = (
    "You are an expert career advisor evaluating job fit for a senior product manager. "
    "You are acting as a ground-truth oracle — be precise and critical. "
    "Return ONLY valid JSON: {\"score\": <float 0.0-1.0>, \"rationale\": \"<2-3 sentences>\"}. "
    "Score guide: 0.85+ exceptional fit, 0.65-0.85 strong, 0.45-0.65 moderate, below 0.45 weak. "
    "Consider: seniority match, domain fit, required vs nice-to-have skills, location/remote flexibility."
)


def _oracle_prompt(row: dict, context_excerpt: str) -> str:
    location = row.get("location") or "not specified"
    return (
        f"Role: {row.get('title', '?')} at {row.get('company', '?')} ({location})\n"
        f"Description: {row.get('description_snippet', '(none)')}\n\n"
        f"Candidate background:\n{context_excerpt}"
    )


def _parse_score(raw: str) -> Optional[tuple[float, str]]:
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)
    try:
        data = json.loads(cleaned)
        score = float(data.get("score", -1))
        rationale = str(data.get("rationale", ""))
        if 0.0 <= score <= 1.0:
            return score, rationale
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    score_m = re.search(r'"score"\s*:\s*([0-9.]+)', cleaned)
    rat_m = re.search(r'"rationale"\s*:\s*"([^"]*)"', cleaned)
    if score_m and rat_m:
        return float(score_m.group(1)), rat_m.group(1)
    return None


def _sample_jobs(rows: list[dict], n: int) -> list[dict]:
    """Return n jobs: top half by score + random from the rest, deduplicated."""
    valid = [r for r in rows if r.get("score", "") != ""]
    try:
        valid.sort(key=lambda r: float(r.get("score", 0)), reverse=True)
    except (TypeError, ValueError):
        pass

    top_n = n // 2
    rest_n = n - top_n
    top = valid[:top_n]
    rest = valid[top_n:]
    sample = top + random.sample(rest, min(rest_n, len(rest)))
    return sample


def _print_table(results: list[dict]) -> None:
    sep = "-" * 120
    header = f"{'#':<3} {'Title':<35} {'Company':<18} {'Run':>5} {'Oracle':>6} {'Delta':>6}"
    print(sep)
    print(header)
    print(sep)
    for i, r in enumerate(results, 1):
        run_score = r.get("run_score", "")
        oracle_score = r.get("oracle_score")
        delta = ""
        flag = ""
        if isinstance(oracle_score, float) and run_score != "":
            try:
                delta_val = oracle_score - float(run_score)
                delta = f"{delta_val:+.2f}"
                flag = " !" if abs(delta_val) > 0.30 else ""
            except (TypeError, ValueError):
                delta = "n/a"

        run_str = f"{float(run_score):.2f}" if run_score != "" else "n/a"
        oracle_str = f"{oracle_score:.2f}" if isinstance(oracle_score, float) else "err"
        title = (r.get("title") or "")[:34]
        company = (r.get("company") or "")[:17]
        print(f"{i:<3} {title:<35} {company:<18} {run_str:>5} {oracle_str:>6} {delta:>6}{flag}")

    print(sep)


def _print_rationales(results: list[dict]) -> None:
    for i, r in enumerate(results, 1):
        print(f"\n[{i}] {r.get('title')} @ {r.get('company')}")
        print(f"  Run rationale    : {r.get('run_rationale') or '(none — v1 CSV)'}")
        print(f"  Oracle rationale : {r.get('oracle_rationale') or '(error)'}")


def _summary_stats(results: list[dict]) -> None:
    pairs = []
    for r in results:
        try:
            run_s = float(r.get("run_score", ""))
            oracle_s = r.get("oracle_score")
            if isinstance(oracle_s, float):
                pairs.append((run_s, oracle_s))
        except (TypeError, ValueError):
            pass

    if not pairs:
        print("\nNo valid pairs to compute statistics.")
        return

    deltas = [abs(o - r) for r, o in pairs]
    mae = sum(deltas) / len(deltas)
    large_disagreements = sum(1 for d in deltas if d > 0.30)

    # Spearman rank correlation (manual — no scipy required).
    n = len(pairs)
    if n > 1:
        run_ranks = _ranks([p[0] for p in pairs])
        oracle_ranks = _ranks([p[1] for p in pairs])
        d_sq = sum((r - o) ** 2 for r, o in zip(run_ranks, oracle_ranks))
        spearman = 1 - (6 * d_sq) / (n * (n ** 2 - 1))
    else:
        spearman = float("nan")

    print(f"\nSummary ({len(pairs)} jobs scored):")
    print(f"  Mean absolute error  : {mae:.3f}")
    print(f"  Spearman correlation : {spearman:.3f}  (1.0 = perfect rank agreement)")
    print(f"  Large disagreements  : {large_disagreements} (delta > 0.30)")


def _ranks(values: list[float]) -> list[float]:
    """Return average ranks for a list of values (handles ties)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) - 1 and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval scoring-v2 quality against an oracle LLM.")
    parser.add_argument("csv_path", help="Path to a run CSV (e.g. outputs/run_*.csv)")
    parser.add_argument(
        "--sample", "-n", type=int, default=20,
        help="Number of jobs to sample for oracle scoring (default: 20)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )
    parser.add_argument(
        "--rationales", action="store_true",
        help="Print full rationales for each job after the table",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    random.seed(args.seed)

    # Load agent context.
    from pm_job_agent.config.settings import get_settings
    settings = get_settings()
    context_path = settings.agent_context_path
    if not context_path.exists():
        print(f"Warning: agent context not found at {context_path}. Oracle prompt will lack background.")
        context_text = ""
    else:
        context_text = context_path.read_text(encoding="utf-8")
    context_excerpt = context_text[:_CONTEXT_MAX_CHARS]

    # Load the oracle LLM (uses DEFAULT_LLM_PROVIDER, not scoring-specific settings).
    from pm_job_agent.models.llm import get_llm_client
    oracle_llm = get_llm_client()
    print(f"Oracle LLM: {settings.default_llm_provider} / {_model_name(settings)}")

    # Read and sample CSV.
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"CSV: {csv_path.name}  ({len(rows)} total rows)")

    sample = _sample_jobs(rows, args.sample)
    print(f"Sampling {len(sample)} jobs (top {args.sample // 2} + random {len(sample) - args.sample // 2}).\n")

    # Score each sampled job with the oracle.
    results = []
    for row in sample:
        prompt = _oracle_prompt(row, context_excerpt)
        try:
            raw = oracle_llm.generate(prompt, system_prompt=_ORACLE_SYSTEM)
            parsed = _parse_score(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"  Oracle call failed for {row.get('title')}: {exc}")
            parsed = None

        oracle_score = parsed[0] if parsed else None
        oracle_rationale = parsed[1] if parsed else None
        results.append({
            "title": row.get("title"),
            "company": row.get("company"),
            "run_score": row.get("score", ""),
            "run_rationale": row.get("score_rationale", ""),
            "oracle_score": oracle_score,
            "oracle_rationale": oracle_rationale,
        })
        status = f"{oracle_score:.2f}" if oracle_score is not None else "FAILED"
        print(f"  Scored: {row.get('title', '?')[:50]} → oracle={status}")

    print()
    _print_table(results)
    if args.rationales:
        _print_rationales(results)
    _summary_stats(results)


def _model_name(settings) -> str:
    provider = (settings.default_llm_provider or "stub").lower()
    mapping = {
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
        "ollama": settings.ollama_model,
    }
    return mapping.get(provider, "n/a")


if __name__ == "__main__":
    main()
