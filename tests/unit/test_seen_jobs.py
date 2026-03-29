"""Tests for the seen_jobs service (load, save, TTL eviction, helpers)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from pm_job_agent.services.seen_jobs import (
    add_job_ids,
    find_new_ids,
    load_seen,
    save_seen,
)


# ---------------------------------------------------------------------------
# load_seen
# ---------------------------------------------------------------------------

class TestLoadSeen:
    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        result = load_seen(tmp_path / "nonexistent.json")
        assert result == {}

    def test_loads_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        today = date.today().isoformat()
        path.write_text(json.dumps({"job:1": today, "job:2": today}))

        result = load_seen(path)
        assert "job:1" in result
        assert "job:2" in result

    def test_evicts_entries_older_than_ttl(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        old_date = (date.today() - timedelta(days=61)).isoformat()
        fresh_date = date.today().isoformat()
        path.write_text(json.dumps({"old:1": old_date, "fresh:1": fresh_date}))

        result = load_seen(path, ttl_days=60)
        assert "old:1" not in result
        assert "fresh:1" in result

    def test_keeps_entries_exactly_at_ttl_boundary(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        boundary_date = (date.today() - timedelta(days=60)).isoformat()
        path.write_text(json.dumps({"boundary:1": boundary_date}))

        result = load_seen(path, ttl_days=60)
        assert "boundary:1" in result

    def test_returns_empty_on_malformed_json(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        path.write_text("not valid json {{{")

        result = load_seen(path)
        assert result == {}

    def test_keeps_entry_with_malformed_date(self, tmp_path: Path) -> None:
        """A corrupted date string should not cause eviction — keep it to be safe."""
        path = tmp_path / "seen.json"
        path.write_text(json.dumps({"job:1": "not-a-date"}))

        result = load_seen(path, ttl_days=60)
        assert "job:1" in result

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        path.write_text("{}")

        result = load_seen(path)
        assert result == {}


# ---------------------------------------------------------------------------
# save_seen
# ---------------------------------------------------------------------------

class TestSaveSeen:
    def test_writes_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        seen = {"job:1": "2026-03-29"}
        save_seen(path, seen)

        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == seen

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "seen.json"
        save_seen(path, {})
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "seen.json"
        save_seen(path, {"old:1": "2025-01-01"})
        save_seen(path, {"new:1": "2026-03-29"})

        loaded = json.loads(path.read_text())
        assert "old:1" not in loaded
        assert "new:1" in loaded


# ---------------------------------------------------------------------------
# add_job_ids
# ---------------------------------------------------------------------------

class TestAddJobIds:
    def test_adds_new_ids_with_today(self) -> None:
        result = add_job_ids({}, ["job:1", "job:2"])
        today = date.today().isoformat()
        assert result == {"job:1": today, "job:2": today}

    def test_does_not_overwrite_existing_date(self) -> None:
        existing = {"job:1": "2025-01-15"}
        result = add_job_ids(existing, ["job:1", "job:2"])
        assert result["job:1"] == "2025-01-15"

    def test_returns_new_dict_does_not_mutate(self) -> None:
        original = {"job:1": "2026-01-01"}
        result = add_job_ids(original, ["job:2"])
        assert "job:2" not in original
        assert "job:2" in result

    def test_empty_ids_returns_copy_of_existing(self) -> None:
        existing = {"job:1": "2026-01-01"}
        result = add_job_ids(existing, [])
        assert result == existing


# ---------------------------------------------------------------------------
# find_new_ids
# ---------------------------------------------------------------------------

class TestFindNewIds:
    def test_returns_ids_not_in_seen(self) -> None:
        seen = {"job:1": "2026-03-01"}
        result = find_new_ids(seen, ["job:1", "job:2", "job:3"])
        assert result == ["job:2", "job:3"]

    def test_all_new_when_seen_is_empty(self) -> None:
        result = find_new_ids({}, ["job:1", "job:2"])
        assert result == ["job:1", "job:2"]

    def test_all_seen_returns_empty_list(self) -> None:
        seen = {"job:1": "2026-03-01", "job:2": "2026-03-01"}
        result = find_new_ids(seen, ["job:1", "job:2"])
        assert result == []

    def test_empty_job_ids_returns_empty_list(self) -> None:
        result = find_new_ids({"job:1": "2026-03-01"}, [])
        assert result == []

    def test_preserves_order(self) -> None:
        seen = {"job:2": "2026-03-01"}
        result = find_new_ids(seen, ["job:1", "job:2", "job:3"])
        assert result == ["job:1", "job:3"]
