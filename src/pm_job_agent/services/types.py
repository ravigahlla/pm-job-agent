"""Shared structured types for jobs flowing through the pipeline."""

from __future__ import annotations

from typing import TypedDict


class _JobDictBase(TypedDict):
    id: str
    title: str
    company: str
    url: str
    source: str
    description_snippet: str


class JobDict(_JobDictBase, total=False):
    # Optional fields — not all sources provide these.
    location: str
    # LinkedIn / Apify: relative text e.g. "2 weeks ago", when provided by the actor.
    source_posted_at: str
    # ISO timestamp from the scraper, when provided.
    source_scraped_at: str
    # Normalized age in hours used by freshness filtering/ranking.
    freshness_age_hours: float
    # Where freshness_age_hours came from: source_posted_at | first_seen | unknown.
    freshness_basis: str


class _RankedJobDictBase(JobDict):
    score: float  # always present; required


class RankedJobDict(_RankedJobDictBase, total=False):
    # Human-readable 1-2 sentence explanation from the LLM.
    # Empty when keyword pre-filter disqualified the job before LLM scoring.
    score_rationale: str


class DocumentDict(TypedDict):
    """Generated resume note and cover letter opening for a single job."""

    job_id: str
    resume_note: str
    cover_letter: str
