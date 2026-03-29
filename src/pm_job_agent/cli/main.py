"""CLI entrypoints.

Commands:
  pm-job-agent run              Run the discovery → scoring → digest → CSV pipeline.
  pm-job-agent generate <csv>   Generate documents for flagged rows in a run CSV.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pm_job_agent.cli.generate_cmd import run_generate
from pm_job_agent.graphs import build_core_loop_graph


def _cmd_run(args: argparse.Namespace) -> None:
    app = build_core_loop_graph()
    result = app.invoke({})

    if args.json:
        print(json.dumps(result, indent=2))
        return

    ranked = result.get("ranked_jobs") or []
    digest = result.get("digest") or ""
    output_path = result.get("output_path") or ""

    print(f"\nJobs found: {len(ranked)}")
    if ranked:
        print("\nTop results:")
        for job in ranked[:5]:
            loc = f" — {job['location']}" if job.get("location") else ""
            print(f"  [{job['score']:.2f}] {job['title']} @ {job['company']}{loc}")
            print(f"         {job['url']}")
    print(f"\nDigest: {digest}")
    if output_path:
        print(f"\nOutput: {output_path}")
        print("\nReview the CSV, set 'flagged' to 'yes' for roles you want to apply to,")
        print(f"then run: pm-job-agent generate {output_path}")


def _cmd_generate(args: argparse.Namespace) -> None:
    run_generate(Path(args.csv))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="pm-job-agent: discover, score, and generate tailored application materials.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Discover jobs, score them, produce a digest, and export a ranked CSV.",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print final graph state as JSON (includes agent_context; treat as sensitive).",
    )
    run_parser.set_defaults(func=_cmd_run)

    # --- generate ---
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate resume notes and cover letters for rows flagged in a run CSV.",
    )
    gen_parser.add_argument(
        "csv",
        metavar="<csv>",
        help="Path to a run CSV produced by `pm-job-agent run`.",
    )
    gen_parser.set_defaults(func=_cmd_generate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
