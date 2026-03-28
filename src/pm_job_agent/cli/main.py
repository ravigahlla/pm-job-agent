"""CLI entrypoints."""

from __future__ import annotations

import argparse
import json

from pm_job_agent.graphs import build_core_loop_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pm-job-agent core loop once.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print final graph state as JSON (includes agent_context; treat as sensitive).",
    )
    args = parser.parse_args()
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


if __name__ == "__main__":
    main()
