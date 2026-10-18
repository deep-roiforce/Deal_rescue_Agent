"""The real LangGraph topology.

Skipped when the `graph` extra is not installed -- the honesty rules are covered
by `test_pipeline.py` either way.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="install with: pip install -e '.[graph]'")

from deal_rescue.graph import build_graph, run_rescue  # noqa: E402
from tests.conftest import MERIDIAN_ACCOUNT, MERIDIAN_ID  # noqa: E402


def test_graph_compiles_with_the_expected_nodes(settings):
    graph = build_graph(settings)
    nodes = set(graph.get_graph().nodes)

    for expected in (
        "fetch_org",
        "fetch_web",
        "fetch_transcript",
        "assemble",
        "synthesize",
        "validate",
        "publish",
    ):
        assert expected in nodes


def test_fetchers_fan_out_from_start(settings):
    edges = {(edge.source, edge.target) for edge in build_graph(settings).get_graph().edges}

    assert ("__start__", "fetch_org") in edges
    assert ("__start__", "fetch_web") in edges
    assert ("__start__", "fetch_transcript") in edges
    # fan-in: all three converge before synthesis
    assert ("fetch_org", "assemble") in edges
    assert ("fetch_web", "assemble") in edges
    assert ("fetch_transcript", "assemble") in edges


def test_run_rescue_publishes_meridian(settings, golden):
    state = run_rescue(MERIDIAN_ID, MERIDIAN_ACCOUNT, settings)

    assert state["status"] == "published"
    assert state["synthesis"]["deal_score"] == golden["deal_score"]
    assert state["replay_url"]
