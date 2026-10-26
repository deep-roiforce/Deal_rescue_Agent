"""Mode switch for the transcript tool."""

from __future__ import annotations

from deal_rescue.settings import Settings, ToolMode, get_settings
from deal_rescue.tools.transcript.contract import TranscriptTool

TOOL_NAME = "transcript"


def get_tool(settings: Settings | None = None) -> TranscriptTool:
    settings = settings or get_settings()
    if settings.mode_for(TOOL_NAME) is ToolMode.LIVE:
        from deal_rescue.tools.transcript.live import LiveTranscript

        return LiveTranscript(settings)

    from deal_rescue.tools.transcript.fake import FakeTranscript

    return FakeTranscript(settings.fixtures_dir)
