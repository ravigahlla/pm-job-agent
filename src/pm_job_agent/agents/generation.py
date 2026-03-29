"""Generate tailored resume notes and cover letter openings for specific jobs.

Called on demand via `pm-job-agent generate <csv>` — not part of the core loop.
Two LLM calls are made per job:
  1. resume_note   — 3–4 bullet points on what to emphasise/reframe in a tailored resume
  2. cover_letter  — opening paragraph (3–4 sentences) for a cover letter

Both outputs are run through redact_pii() before being stored, so contact
details from agent-context.md never reach the output files even if the LLM
reproduces them.
"""

from __future__ import annotations

import logging

from pm_job_agent.models.llm import LLMClient
from pm_job_agent.services.redaction import redact_pii
from pm_job_agent.services.types import DocumentDict, RankedJobDict

logger = logging.getLogger(__name__)

# Cap context sent to the LLM to keep token usage predictable.
# The full agent-context.md is often several thousand chars; the most relevant
# signal is typically in the first section. Phase 2 can do smarter chunking.
_CONTEXT_MAX_CHARS = 1500

_RESUME_SYSTEM = (
    "You are a career coach helping a product manager tailor their resume for a specific role. "
    "Output 3–4 concise bullet points identifying specific experiences, metrics, or skills "
    "from the candidate's background that should be emphasised or reframed for this role. "
    "Do not include phone numbers, email addresses, or physical mailing addresses."
)

_COVER_SYSTEM = (
    "You are a career coach helping a product manager write targeted cover letters. "
    "Write in first person from the candidate's perspective. "
    "Be specific, compelling, and concise — no more than 4 sentences. "
    "Do not include phone numbers, email addresses, or physical mailing addresses."
)


def _resume_prompt(job: dict, context_excerpt: str) -> str:
    return (
        f"Role: {job['title']} at {job['company']}\n"
        f"Job snippet: {job.get('description_snippet', '(none)')}\n\n"
        f"Candidate background:\n{context_excerpt}\n\n"
        "List 3–4 specific resume tailoring points for this application."
    )


def _cover_prompt(job: dict, context_excerpt: str) -> str:
    return (
        f"Role: {job['title']} at {job['company']}\n"
        f"Job snippet: {job.get('description_snippet', '(none)')}\n\n"
        f"Candidate background:\n{context_excerpt}\n\n"
        "Write a compelling opening paragraph for a cover letter applying to this role."
    )


def generate_for_jobs(
    jobs: list[RankedJobDict],
    context: str,
    llm: LLMClient,
) -> list[DocumentDict]:
    """Generate resume notes and cover letters for the given jobs.

    Called directly by the generate command with a pre-filtered list of jobs
    (those the user has flagged for application). No threshold logic here —
    the caller decides which jobs to pass in.
    """
    context_excerpt = context[:_CONTEXT_MAX_CHARS]
    documents: list[DocumentDict] = []

    for job in jobs:
        raw_resume = llm.generate(_resume_prompt(job, context_excerpt), system_prompt=_RESUME_SYSTEM)
        raw_cover = llm.generate(_cover_prompt(job, context_excerpt), system_prompt=_COVER_SYSTEM)
        documents.append(
            DocumentDict(
                job_id=job["id"],
                resume_note=redact_pii(raw_resume),
                cover_letter=redact_pii(raw_cover),
            )
        )
        logger.debug("Generated documents for job %s (%s)", job["id"], job["title"])

    logger.info("Generated documents for %d job(s)", len(documents))
    return documents
