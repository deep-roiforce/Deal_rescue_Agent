"""Typed contract for the Salesforce write-back.

Everything the run produced lands back in the org as records: the score with its
signals, the drafted email, the replay link, and one audit Task per external
finding with its source. The audit trail is the thesis of the demo -- a rep can
see exactly which outside claim drove which sentence (spec 4.2 N8b).

Approval and send happen after this, natively in Salesforce (D8). The
orchestrator has no send path and never will.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

# Org-side API names. Change here if the org build uses different ones.
FIELD_SCORE = "Rescue_Score__c"
FIELD_SIGNALS = "Rescue_Signals__c"
FIELD_REPLAY_URL = "Replay_URL__c"
FIELD_APPROVED = "Rescue_Draft_Approved__c"
FIELD_EVIDENCE_LEVEL = "Rescue_Evidence_Level__c"
FIELD_EXTERNAL_ID = "Rescue_Run_Key__c"

# Salesforce hard limits we must respect before the insert, not after it.
TASK_SUBJECT_MAX = 255


def make_run_key(deal_id: str, as_of: date) -> str:
    """Idempotency key for one deal on one day.

    Re-running a rescue must not litter the Opportunity with duplicate audit
    Tasks. With `Rescue_Run_Key__c` marked External Id on Task, the write-back
    upserts instead of inserting -- see docs/salesforce-app.md.
    """
    return f"{deal_id}-{as_of.isoformat()}"


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str          # "web:<id>" | "transcript:<date>" | "opp_history"
    title: str
    url: str | None = None
    date: str | None = None
    signal_type: str | None = None


class DraftEmail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    to_contact_id: str
    to_name: str
    subject: str
    body: str
    grounding_note: str = ""
    low_context_flag: bool = False


class WritebackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_id: str
    score: int
    signals: list[str] = Field(default_factory=list)
    replay_url: str | None = None
    email_draft: DraftEmail | None = None
    evidence_level: str = "full"
    audit_findings: list[AuditFinding] = Field(default_factory=list)
    run_key: str = ""  # idempotency; see make_run_key()


class WritebackResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    opportunity_updated: bool = False
    rescue_result_id: str | None = None
    draft_task_id: str | None = None
    audit_task_ids: list[str] = Field(default_factory=list)

    def as_state(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SalesforceWritebackTool(Protocol):
    def create_rescue_writeback(self, payload: WritebackPayload) -> WritebackResult: ...


def audit_findings_from_state(
    web_findings: dict[str, Any] | None, transcript: dict[str, Any] | None
) -> list[AuditFinding]:
    """One audit record per external claim the synthesis was allowed to use."""
    findings: list[AuditFinding] = []

    for item in (web_findings or {}).get("items", []) or []:
        findings.append(
            AuditFinding(
                source=f"web:{item['id']}",
                title=item.get("title", ""),
                url=item.get("url"),
                date=item.get("date"),
                signal_type=item.get("signal_type"),
            )
        )

    if (transcript or {}).get("found"):
        findings.append(
            AuditFinding(
                source=f"transcript:{transcript.get('meeting_date')}",
                title=transcript.get("doc_title") or "Meeting transcript",
                url=(
                    f"https://docs.google.com/document/d/{transcript['doc_id']}"
                    if transcript.get("doc_id")
                    else None
                ),
                date=transcript.get("meeting_date"),
                signal_type="transcript",
            )
        )

    return findings
