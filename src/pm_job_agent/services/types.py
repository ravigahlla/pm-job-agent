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


class RankedJobDict(JobDict):
    score: float


class DocumentDict(TypedDict):
    """Generated resume note and cover letter opening for a single job."""

    job_id: str
    resume_note: str
    cover_letter: str
