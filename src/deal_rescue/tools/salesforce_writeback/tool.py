"""Mode switch for the salesforce_writeback tool."""

from __future__ import annotations

from deal_rescue.settings import Settings, ToolMode, get_settings
from deal_rescue.tools.salesforce_writeback.contract import SalesforceWritebackTool

TOOL_NAME = "salesforce_writeback"


def get_tool(settings: Settings | None = None) -> SalesforceWritebackTool:
    settings = settings or get_settings()
    if settings.mode_for(TOOL_NAME) is ToolMode.LIVE:
        from deal_rescue.tools.salesforce_writeback.live import LiveSalesforceWriteback

        return LiveSalesforceWriteback(settings)

    from deal_rescue.tools.salesforce_writeback.fake import FakeSalesforceWriteback

    return FakeSalesforceWriteback(settings.state_dir)
