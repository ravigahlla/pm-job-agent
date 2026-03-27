"""CLI entrypoints."""

from __future__ import annotations

import argparse
import json
from pprint import pprint

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
    else:
        pprint(result)


if __name__ == "__main__":
    main()
