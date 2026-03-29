"""Compile the discover → score → digest → persist pipeline.

Document generation is intentionally absent from this graph. Run
`pm-job-agent generate <csv>` after reviewing the output CSV to generate
tailored documents for only the roles you flag.
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from pm_job_agent.agents.context import load_agent_context
from pm_job_agent.agents.digest import make_digest_node
from pm_job_agent.agents.discovery import discover_jobs
from pm_job_agent.agents.persist import persist_jobs
from pm_job_agent.agents.scoring import score_jobs
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.models.llm import LLMClient, get_llm_client


def build_core_loop_graph(llm: Optional[LLMClient] = None):
    """Wire LangGraph nodes. Integrations attach at `discover_jobs` later."""
    client = llm or get_llm_client()
    graph = StateGraph(CoreLoopState)
    graph.add_node("load_context", load_agent_context)
    graph.add_node("discover", discover_jobs)
    graph.add_node("score", score_jobs)
    graph.add_node("digest", make_digest_node(client))
    graph.add_node("persist", persist_jobs)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "discover")
    graph.add_edge("discover", "score")
    graph.add_edge("score", "digest")
    graph.add_edge("digest", "persist")
    graph.add_edge("persist", END)
    return graph.compile()
