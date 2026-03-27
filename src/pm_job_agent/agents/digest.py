"""Turn ranked jobs + context into a short narrative via the LLM client."""

from __future__ import annotations

from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.models.llm import LLMClient


def digest_jobs(state: CoreLoopState, *, llm: LLMClient) -> dict:
    ctx = state.get("agent_context") or ""
    ranked = state.get("ranked_jobs") or []
    lines = [f"- {j['title']} @ {j['company']} (score={j['score']})" for j in ranked[:10]]
    block = "\n".join(lines) if lines else "(no jobs this run)"
    prompt = f"Career context length: {len(ctx)} characters.\nRanked jobs:\n{block}"
    digest = llm.generate(
        prompt,
        system_prompt="Summarize job-search fit in two short sentences for the candidate.",
    )
    return {"digest": digest}


def make_digest_node(llm: LLMClient):
    def _node(state: CoreLoopState) -> dict:
        return digest_jobs(state, llm=llm)

    return _node
