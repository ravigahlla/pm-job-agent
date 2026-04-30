"""Compile the discover → score → deduplicate → digest → persist → sync_sheets → notify pipeline.

Discovery aggregates Greenhouse, Lever, Ashby (when configured), and LinkedIn (when Apify is set).

Document generation is intentionally absent from this graph. Run
`pm-job-agent generate <csv>` after reviewing the output CSV to generate
tailored documents for only the roles you flag.
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from pm_job_agent.agents.context import load_agent_context
from pm_job_agent.agents.deduplicate import make_deduplicate_node
from pm_job_agent.agents.digest import make_digest_node
from pm_job_agent.agents.discovery import discover_jobs
from pm_job_agent.agents.notify import make_notify_node
from pm_job_agent.agents.persist import persist_jobs
from pm_job_agent.agents.sync_sheets import make_sync_sheets_node
from pm_job_agent.agents.scoring import make_score_node
from pm_job_agent.config.settings import get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.models.llm import LLMClient, get_llm_client, get_scoring_llm_client


def build_core_loop_graph(llm: Optional[LLMClient] = None):
    """Wire LangGraph nodes. Integrations attach at `discover_jobs` later."""
    client = llm or get_llm_client()
    # Scoring uses its own model (SCORING_LLM_PROVIDER / SCORING_MODEL in .env), which
    # defaults to DEFAULT_LLM_PROVIDER when those vars are unset. Passing llm explicitly
    # (e.g. StubLLM in tests) overrides both — that keeps test behaviour deterministic.
    scoring_client = llm or get_scoring_llm_client()
    settings = get_settings()
    graph = StateGraph(CoreLoopState)
    graph.add_node("load_context", load_agent_context)
    graph.add_node("discover", discover_jobs)
    graph.add_node("score", make_score_node(scoring_client))
    graph.add_node("deduplicate", make_deduplicate_node(settings))
    graph.add_node("digest", make_digest_node(client))
    graph.add_node("persist", persist_jobs)
    graph.add_node("sync_sheets", make_sync_sheets_node(settings))
    graph.add_node("notify", make_notify_node(settings))
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "discover")
    graph.add_edge("discover", "score")
    graph.add_edge("score", "deduplicate")
    graph.add_edge("deduplicate", "digest")
    graph.add_edge("digest", "persist")
    graph.add_edge("persist", "sync_sheets")
    graph.add_edge("sync_sheets", "notify")
    graph.add_edge("notify", END)
    return graph.compile()
