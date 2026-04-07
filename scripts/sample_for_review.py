#!/usr/bin/env python3
"""Stratified sampling script for human evaluation of LLM scoring quality.

Pools all outputs/run_*.csv files, bins jobs into score buckets, draws a
random sample from each bucket, and exports to private/sample_for_review.csv.

Usage:
    python scripts/sample_for_review.py                 # 3 samples per bucket
    python scripts/sample_for_review.py --n 5           # 5 samples per bucket
    python scripts/sample_for_review.py --seed 42       # reproducible sample
    python scripts/sample_for_review.py --csv-only      # skip terminal output

Workflow:
    1. Run this script to generate private/sample_for_review.csv
    2. Open the CSV and fill in `your_score` (1-5) and `your_notes` for each job
    3. Look for patterns where LLM scores diverge from yours
    4. Update private/scoring_criteria.md to correct those patterns
    5. Re-score with: python scripts/rescore_sheet.py --write

Output columns in the CSV:
    bucket, score, title, company, location, url, score_rationale,
    your_score, your_notes
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

# Score bucket thresholds — (name, low_inclusive, high_exclusive)
_BUCKETS: list[tuple[str, float, float]] = [
    ("STRONG",     0.75, 1.01),
    ("PROMISING",  0.55, 0.75),
    ("BORDERLINE", 0.35, 0.55),
    ("WEAK",       0.00, 0.35),
]

_OUTPUT_COLUMNS = [
    "bucket",
    "score",
    "title",
    "company",
    "location",
    "url",
    "score_rationale",
    "your_score",
    "your_notes",
]

_DIVIDER = "─" * 70


def load_all_jobs(outputs_dir: Path) -> list[dict]:
    """Read all run_*.csv files, deduplicate by job id, return job dicts."""
    seen_ids: set[str] = set()
    jobs: list[dict] = []

    csv_files = sorted(outputs_dir.glob("run_*.csv"))
    if not csv_files:
        print(f"No run_*.csv files found in {outputs_dir}", file=sys.stderr)
        sys.exit(1)

    for csv_path in csv_files:
        with csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                job_id = row.get("id", "").strip()
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                raw_score = row.get("score", "").strip()
                try:
                    score = float(raw_score)
                except ValueError:
                    continue  # skip rows without a numeric score

                jobs.append({
                    "id":              job_id,
                    "score":           score,
                    "title":           row.get("title", "").strip(),
                    "company":         row.get("company", "").strip(),
                    "location":        row.get("location", "").strip(),
                    "url":             row.get("url", "").strip(),
                    "score_rationale": row.get("score_rationale", "").strip(),
                })

    return jobs


def bin_into_buckets(jobs: list[dict]) -> dict[str, list[dict]]:
    """Assign each job to its score bucket."""
    buckets: dict[str, list[dict]] = {name: [] for name, _, _ in _BUCKETS}
    for job in jobs:
        for name, lo, hi in _BUCKETS:
            if lo <= job["score"] < hi:
                job["bucket"] = name
                buckets[name].append(job)
                break
    return buckets


def sample_buckets(
    buckets: dict[str, list[dict]],
    n: int,
    seed: int | None,
) -> list[dict]:
    """Draw up to n jobs per bucket, ordered strong → weak."""
    rng = random.Random(seed)
    sampled: list[dict] = []
    for name, _, _ in _BUCKETS:
        pool = buckets.get(name, [])
        draw = rng.sample(pool, min(n, len(pool)))
        draw.sort(key=lambda j: j["score"], reverse=True)
        sampled.extend(draw)
    return sampled


def print_job(job: dict, idx: int, total: int) -> None:
    """Print a single job to the terminal."""
    bucket = job.get("bucket", "")
    score  = job["score"]
    print(f"\n{_DIVIDER}")
    print(f"  [{idx}/{total}]  [{bucket}  {score:.2f}]  {job['title']} @ {job['company']}")
    print(_DIVIDER)
    if job["location"]:
        print(f"  Location:  {job['location']}")
    if job["url"]:
        print(f"  URL:       {job['url']}")
    if job["score_rationale"]:
        rationale = job["score_rationale"]
        print(f"\n  Rationale: {rationale[:300]}{'...' if len(rationale) > 300 else ''}")
    print()


def write_csv(sample: list[dict], output_path: Path) -> None:
    """Write the sample to the output CSV with blank your_score / your_notes columns."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for job in sample:
            writer.writerow({
                "bucket":          job.get("bucket", ""),
                "score":           f"{job['score']:.2f}",
                "title":           job["title"],
                "company":         job["company"],
                "location":        job["location"],
                "url":             job["url"],
                "score_rationale": job["score_rationale"],
                "your_score":      "",
                "your_notes":      "",
            })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stratified sample of scored jobs for human evaluation."
    )
    parser.add_argument(
        "--n", type=int, default=3,
        help="Number of jobs to sample per score bucket (default: 3).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--csv-only", action="store_true",
        help="Skip terminal output — just write the CSV.",
    )
    parser.add_argument(
        "--outputs-dir", type=Path, default=Path("outputs"),
        help="Directory containing run_*.csv files (default: outputs/).",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("private/sample_for_review.csv"),
        help="Destination CSV (default: private/sample_for_review.csv).",
    )
    args = parser.parse_args()

    jobs    = load_all_jobs(args.outputs_dir)
    buckets = bin_into_buckets(jobs)
    sample  = sample_buckets(buckets, n=args.n, seed=args.seed)

    if not sample:
        print("No jobs found to sample.", file=sys.stderr)
        sys.exit(1)

    print(f"\nLoaded {len(jobs)} unique jobs from {args.outputs_dir}/")
    print(f"Sampled {len(sample)} jobs ({args.n} per bucket):\n")
    for name, _, _ in _BUCKETS:
        pool_size = len(buckets.get(name, []))
        drawn     = sum(1 for j in sample if j.get("bucket") == name)
        print(f"  {name:<12} {drawn} of {pool_size}")
    print()

    if not args.csv_only:
        for idx, job in enumerate(sample, start=1):
            print_job(job, idx, len(sample))

    write_csv(sample, args.output)
    print(f"Saved to: {args.output}")
    print("\nNext steps:")
    print("  1. Open the CSV and fill in `your_score` (1-5) and `your_notes`")
    print("  2. Look for patterns where LLM scores diverge from yours")
    print("  3. Update private/scoring_criteria.md to correct those patterns")
    print("  4. Re-score: python scripts/rescore_sheet.py --write\n")


if __name__ == "__main__":
    main()
