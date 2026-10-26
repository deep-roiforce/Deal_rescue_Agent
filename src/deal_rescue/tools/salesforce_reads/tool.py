"""Mode switch for the salesforce_reads tool."""

from __future__ import annotations

from deal_rescue.settings import Settings, ToolMode, get_settings
from deal_rescue.tools.salesforce_reads.contract import SalesforceReadsTool

TOOL_NAME = "salesforce_reads"


def get_tool(settings: Settings | None = None) -> SalesforceReadsTool:
    settings = settings or get_settings()
    if settings.mode_for(TOOL_NAME) is ToolMode.LIVE:
        from deal_rescue.tools.salesforce_reads.live import LiveSalesforceReads

        return LiveSalesforceReads(settings)

    from deal_rescue.tools.salesforce_reads.fake import FakeSalesforceReads

    return FakeSalesforceReads(settings.fixtures_dir)
