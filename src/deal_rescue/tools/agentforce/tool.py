"""Mode switch for the agentforce tool."""

from __future__ import annotations

from deal_rescue.settings import Settings, ToolMode, get_settings
from deal_rescue.tools.agentforce.contract import AgentforceTool

TOOL_NAME = "agentforce"


def get_tool(settings: Settings | None = None) -> AgentforceTool:
    settings = settings or get_settings()
    if settings.mode_for(TOOL_NAME) is ToolMode.LIVE:
        if settings.synthesis_provider == "anthropic":
            from deal_rescue.tools.agentforce.live import LiveAnthropicSynthesis

            return LiveAnthropicSynthesis(settings)

        from deal_rescue.tools.agentforce.live import LiveAgentforce

        return LiveAgentforce(settings)

    from deal_rescue.tools.agentforce.fake import FakeAgentforce

    return FakeAgentforce(settings.fixtures_dir, fault=settings.agentforce_fake_fault)
