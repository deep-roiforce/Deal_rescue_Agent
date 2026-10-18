"""Tool registry.

One entry per outside system. `tests/test_registry.py` asserts every entry has
the five-file layout described in `base.py`, so a new tool cannot be added
without its own docs and fake.
"""

from __future__ import annotations

from deal_rescue.tools.base import ToolError, ToolNotImplemented, ToolSpec, ToolUnavailable, degraded

REGISTRY: dict[str, ToolSpec] = {
    "salesforce_reads": ToolSpec(
        name="salesforce_reads",
        summary="Opportunity, stage history, contact roles, activity timeline, stalled-deal query.",
        transport="mcp",
        node="fetch_org",
        degrades=False,
        phase="2.1",
    ),
    "web_research": ToolSpec(
        name="web_research",
        summary="News / expansion / people-change / job-posting signals for the account.",
        transport="https",
        node="fetch_web",
        degrades=True,
        phase="2.2",
    ),
    "transcript": ToolSpec(
        name="transcript",
        summary="Most recent Google Meet transcript Doc for the account, excerpted.",
        transport="google-api",
        node="fetch_transcript",
        degrades=True,
        phase="2.3",
    ),
    "agentforce": ToolSpec(
        name="agentforce",
        summary="synthesize_rescue(): merge + judgment, returns SynthesisOutput JSON.",
        transport="mcp",
        node="synthesize",
        degrades=False,
        phase="2.4",
    ),
    "storymydata": ToolSpec(
        name="storymydata",
        summary="create_story(): enriched Deal Replay on the StoryMyData platform.",
        transport="https",
        node="publish",
        degrades=False,
        phase="2.5",
    ),
    "salesforce_writeback": ToolSpec(
        name="salesforce_writeback",
        summary="Score, signals, replay URL, email draft, per-finding audit tasks.",
        transport="mcp",
        node="publish",
        degrades=False,
        phase="2.6",
    ),
}

__all__ = [
    "REGISTRY",
    "ToolSpec",
    "ToolError",
    "ToolUnavailable",
    "ToolNotImplemented",
    "degraded",
]
