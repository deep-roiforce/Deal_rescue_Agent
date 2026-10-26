"""Mode switch for the storymydata tool."""

from __future__ import annotations

from deal_rescue.settings import Settings, ToolMode, get_settings
from deal_rescue.tools.storymydata.contract import StoryMyDataTool

TOOL_NAME = "storymydata"


def get_tool(settings: Settings | None = None) -> StoryMyDataTool:
    settings = settings or get_settings()
    if settings.mode_for(TOOL_NAME) is ToolMode.LIVE:
        from deal_rescue.tools.storymydata.live import LiveStoryMyData

        return LiveStoryMyData(settings)

    from deal_rescue.tools.storymydata.fake import FakeStoryMyData

    return FakeStoryMyData(settings.storymydata_base_url, settings.state_dir)
