"""Tests for the digest summary builder."""

from __future__ import annotations

from pm_job_agent.agents.digest import digest_jobs
from pm_job_agent.models.llm import StubLLM


def _job(job_id: str, *, score: float, title: str = "PM", company: str = "Acme") -> dict:
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "location": "Remote",
        "url": "https://example.com",
        "source": "test",
        "description_snippet": "",
        "score": score,
    }


class TestDigestJobs:
    def test_no_new_jobs_is_deterministic(self) -> None:
        state = {"ranked_jobs": [_job("a", score=0.9)], "new_job_ids": []}
        out = digest_jobs(state, llm=StubLLM())
        assert out["digest"].startswith("New: 0")

    def test_new_jobs_includes_counts(self) -> None:
        state = {
            "ranked_jobs": [
                _job("a", score=0.9, title="High", company="HCo"),
                _job("b", score=0.6, title="Next", company="NCo"),
                _job("c", score=0.2, title="Low", company="LCo"),
            ],
            "new_job_ids": ["a", "b", "c"],
        }
        out = digest_jobs(state, llm=StubLLM())
        # StubLLM won't return JSON; we should hit the deterministic fallback.
        assert "New: 3" in out["digest"]
        assert "High-tier:" in out["digest"]
        assert "Next-tier:" in out["digest"]

    def test_high_signal_highlights_only_high_tier(self) -> None:
        state = {
            "ranked_jobs": [
                _job("a", score=0.9, title="High", company="HCo"),
                _job("b", score=0.6, title="Next", company="NCo"),
            ],
            "new_job_ids": ["a", "b"],
        }
        out = digest_jobs(state, llm=StubLLM())
        assert "High @ HCo" in out["digest"]
        assert "Next @ NCo" not in out["digest"]

