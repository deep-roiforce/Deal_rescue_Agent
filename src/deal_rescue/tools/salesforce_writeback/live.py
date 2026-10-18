"""Live write-back over Salesforce MCP (Phase 2.6).

Shape only -- the record plan is decided, the transport is not wired yet.

Record plan (spec 5.1):
  * Opportunity update: Rescue_Score__c, Rescue_Signals__c, Replay_URL__c
  * One Task holding the drafted email + the approval flag the Flow watches
  * One Task per external finding, each carrying its source URL (the audit trail)

The approval Flow and the native send live entirely in the org (D8).
"""

from __future__ import annotations

from typing import Any

from deal_rescue.settings import Settings
from deal_rescue.tools.base import ToolNotImplemented
from deal_rescue.tools.salesforce_writeback.contract import (
    FIELD_APPROVED,
    FIELD_EVIDENCE_LEVEL,
    FIELD_EXTERNAL_ID,
    FIELD_REPLAY_URL,
    FIELD_SCORE,
    FIELD_SIGNALS,
    TASK_SUBJECT_MAX,
    WritebackPayload,
    WritebackResult,
)

MCP_TOOL_NAME = "create_rescue_writeback"


class LiveSalesforceWriteback:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.sf_mcp_url:
            raise ToolNotImplemented("SF_MCP_URL is not set")

    def _call(self, tool: str, **args: Any) -> Any:
        raise ToolNotImplemented(
            f"Salesforce MCP call '{tool}' not wired yet (Phase 2.6). "
            "Implement with langchain_mcp_adapters against SF_MCP_URL."
        )

    def build_request(self, payload: WritebackPayload) -> dict[str, Any]:
        """The MCP request body. Pure -- unit-tested without a transport."""
        draft = payload.email_draft
        return {
            "deal_id": payload.deal_id,
            "run_key": payload.run_key,
            "opportunity_fields": {
                FIELD_SCORE: payload.score,
                FIELD_SIGNALS: "\n".join(payload.signals),
                FIELD_REPLAY_URL: payload.replay_url,
                FIELD_EVIDENCE_LEVEL: payload.evidence_level,
            },
            "draft_task": (
                {
                    # Task.Subject is 255 -- truncate here, not in the org, so a
                    # long synthesized subject cannot fail the insert.
                    "subject": f"Rescue draft: {draft.subject}"[:TASK_SUBJECT_MAX],
                    "description": draft.body,
                    "who_id": draft.to_contact_id,
                    "what_id": payload.deal_id,
                    "fields": {
                        FIELD_APPROVED: False,
                        FIELD_EXTERNAL_ID: f"{payload.run_key}-draft",
                    },
                    "low_context": draft.low_context_flag,
                }
                if draft
                else None
            ),
            "audit_tasks": [
                {
                    "subject": f"Evidence [{finding.source}] {finding.title}"[:TASK_SUBJECT_MAX],
                    "description": "\n".join(
                        part
                        for part in (finding.url, finding.date, finding.signal_type)
                        if part
                    ),
                    "what_id": payload.deal_id,
                    "fields": {FIELD_EXTERNAL_ID: f"{payload.run_key}-{finding.source}"},
                }
                for finding in payload.audit_findings
            ],
        }

    def create_rescue_writeback(self, payload: WritebackPayload) -> WritebackResult:
        raw = self._call(MCP_TOOL_NAME, **self.build_request(payload))
        return WritebackResult(**raw)
