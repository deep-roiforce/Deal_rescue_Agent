"""N8 -- publish.

(a) the RESCUE BRIEF -- a real, human-readable HTML page (deal summary, the
    evidence, how to save it, the draft) written to .runs/briefs/ and served at
    /briefs/{deal_id}. This is the artifact a person opens.
(b) enriched replay on the StoryMyData platform (live in Phase 2.5),
(c) write-back to Salesforce: score, signals, brief URL, draft, audit records.

Approval and send happen in the org after this. The orchestrator stops here (D8).
"""

from __future__ import annotations

from typing import Any

from deal_rescue.brief import brief_url, save_brief
from deal_rescue.settings import Settings, get_settings
from deal_rescue.tools.salesforce_writeback import (
    DraftEmail,
    WritebackPayload,
    audit_findings_from_state,
    make_run_key,
)
from deal_rescue.tools.salesforce_writeback import get_tool as get_writeback_tool
from deal_rescue.tools.storymydata import get_tool as get_story_tool
from deal_rescue.tools.storymydata import synthesis_to_story_request


def publish(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    synthesis = state["synthesis"]
    org_data = state["org_data"]

    # The human-readable deliverable first: a run the gate passed always leaves
    # a brief a person can open, whatever the downstream platforms do.
    brief_path = save_brief(state, settings)
    brief_link = brief_url(state["deal_id"])

    try:
        story = get_story_tool(settings).create_story(
            synthesis_to_story_request(synthesis, org_data)
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "replay_url": brief_link,
            "brief_path": str(brief_path),
            "status": "failed_publish_story",
            "validation_errors": [f"StoryMyData publish failed: {type(exc).__name__}: {exc}"],
        }

    payload = WritebackPayload(
        deal_id=state["deal_id"],
        score=int(synthesis["deal_score"]["value"]),
        signals=list(synthesis["deal_score"].get("signals", [])),
        replay_url=brief_link,
        email_draft=DraftEmail(**synthesis["email_draft"]),
        evidence_level=synthesis.get("evidence_level", "full"),
        audit_findings=audit_findings_from_state(
            state.get("web_findings"), state.get("transcript")
        ),
        run_key=make_run_key(state["deal_id"], settings.today()),
    )

    try:
        result = get_writeback_tool(settings).create_rescue_writeback(payload)
    except Exception as exc:  # noqa: BLE001
        return {
            "replay_url": brief_link,
            "brief_path": str(brief_path),
            "status": "failed_publish_writeback",
            "validation_errors": [f"Salesforce write-back failed: {type(exc).__name__}: {exc}"],
        }

    return {
        "replay_url": brief_link,
        "brief_path": str(brief_path),
        "story_url": story.url,  # Phase 2.5: becomes a real StoryMyData page
        "writeback": result.as_state(),
        "status": "published",
    }
