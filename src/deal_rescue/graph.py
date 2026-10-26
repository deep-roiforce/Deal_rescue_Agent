"""Graph wiring (spec 4.3).

    START -> fetch_org --------+
    START -> fetch_web --------+--> assemble --> [route] --> synthesize --> validate --> [route]
    START -> fetch_transcript -+                    |                                      |
                                                    +--> END (no org data)   pass -> publish -> END
                                                                            fail(<=2) -> synthesize
                                                                            fail(=3)  -> END

Deterministic graph, fixed nodes and edges. LLM judgment is confined to the
synthesize node. No free-roaming ReAct agents (D10). In-memory checkpointer only;
there is no `interrupt()` because approval lives in Salesforce, not in the graph
(D8).
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from deal_rescue.nodes import (
    assemble,
    fetch_org,
    fetch_transcript,
    fetch_web,
    publish,
    route_after_assemble,
    route_after_validate,
    synthesize,
    validate,
)
from deal_rescue.settings import Settings, get_settings
from deal_rescue.state import RescueState, new_state

FETCHERS = ("fetch_org", "fetch_web", "fetch_transcript")


def build_graph(settings: Settings | None = None):
    settings = settings or get_settings()

    builder = StateGraph(RescueState)
    builder.add_node("fetch_org", partial(fetch_org, settings=settings))
    builder.add_node("fetch_web", partial(fetch_web, settings=settings))
    builder.add_node("fetch_transcript", partial(fetch_transcript, settings=settings))
    builder.add_node("assemble", partial(assemble, settings=settings))
    builder.add_node("synthesize", partial(synthesize, settings=settings))
    builder.add_node("validate", partial(validate, settings=settings))
    builder.add_node("publish", partial(publish, settings=settings))

    for node in FETCHERS:
        builder.add_edge(START, node)
        builder.add_edge(node, "assemble")

    builder.add_conditional_edges(
        "assemble", route_after_assemble, {"synthesize": "synthesize", "end": END}
    )
    builder.add_edge("synthesize", "validate")
    builder.add_conditional_edges(
        "validate",
        partial(route_after_validate, settings=settings),
        {"publish": "publish", "synthesize": "synthesize", "end": END},
    )
    builder.add_edge("publish", END)

    return builder.compile(checkpointer=MemorySaver())


def run_rescue(
    deal_id: str,
    account_name: str,
    settings: Settings | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """One rescue run, start to finish. Returns the final state."""
    import time

    from deal_rescue import runlog

    settings = settings or get_settings()
    graph = build_graph(settings)
    config = {"configurable": {"thread_id": thread_id or f"rescue-{deal_id}"}}
    started = time.monotonic()
    state = dict(graph.invoke(new_state(deal_id, account_name), config=config))
    runlog.record_rescue(state, settings, time.monotonic() - started)
    return state
