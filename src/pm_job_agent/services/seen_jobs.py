"""Persistent store of job IDs seen across pipeline runs.

Format of private/seen_jobs.json:
    {
        "greenhouse:vercel:5808590004": "2026-03-29",
        "linkedin:4373499410":          "2026-03-29"
    }

Key   = job ID (matches the `id` field on JobDict / RankedJobDict).
Value = ISO date the job was first seen.

On every load, entries older than `ttl_days` are evicted so the file
doesn't grow unboundedly. 60 days is the default — a role that was last
seen two months ago is worth surfacing again if it's still listed.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def load_seen(path: Path, ttl_days: int = 60) -> dict[str, str]:
    """Load seen job IDs from *path*, evicting entries older than *ttl_days*.

    Returns an empty dict (and does not crash) if the file does not exist yet.
    """
    if not path.exists():
        return {}

    try:
        raw: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read seen_jobs file (%s) — treating all jobs as new.", exc)
        return {}

    cutoff = date.today() - timedelta(days=ttl_days)
    evicted = 0
    live: dict[str, str] = {}
    for job_id, date_str in raw.items():
        try:
            seen_date = date.fromisoformat(date_str)
        except ValueError:
            # Malformed date — keep it to avoid re-surfacing spuriously.
            live[job_id] = date_str
            continue
        if seen_date >= cutoff:
            live[job_id] = date_str
        else:
            evicted += 1

    if evicted:
        logger.debug("Evicted %d expired entries from seen_jobs (TTL=%d days).", evicted, ttl_days)

    return live


def save_seen(path: Path, seen: dict[str, str]) -> None:
    """Write *seen* back to *path*, creating parent directories as needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write seen_jobs file: %s", exc)


def add_job_ids(seen: dict[str, str], job_ids: list[str]) -> dict[str, str]:
    """Return a new dict with *job_ids* added, using today as the seen date.

    Existing entries are preserved so their original date is not overwritten.
    """
    today = date.today().isoformat()
    updated = dict(seen)
    for job_id in job_ids:
        updated.setdefault(job_id, today)
    return updated


def find_new_ids(seen: dict[str, str], job_ids: list[str]) -> list[str]:
    """Return job IDs from *job_ids* that are NOT present in *seen*."""
    return [jid for jid in job_ids if jid not in seen]
