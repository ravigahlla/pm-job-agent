"""Shared structured types for jobs flowing through the pipeline."""

from __future__ import annotations

from typing import TypedDict


class JobDict(TypedDict):
    id: str
    title: str
    company: str
    url: str
    source: str
    description_snippet: str


class RankedJobDict(JobDict):
    score: float
