"""Mode switch for the web_research tool."""

from __future__ import annotations

from deal_rescue.settings import Settings, ToolMode, get_settings
from deal_rescue.tools.web_research.contract import WebResearchTool

TOOL_NAME = "web_research"


def get_tool(settings: Settings | None = None) -> WebResearchTool:
    settings = settings or get_settings()
    if settings.mode_for(TOOL_NAME) is ToolMode.LIVE:
        from deal_rescue.tools.web_research.live import LiveWebResearch

        return LiveWebResearch(settings)

    from deal_rescue.tools.web_research.fake import FakeWebResearch

    return FakeWebResearch(settings.fixtures_dir)
