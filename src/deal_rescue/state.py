"""Graph state (spec §4.1)."""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class RescueState(TypedDict, total=False):
    deal_id: str
    account_name: str
    org_data: Optional[dict[str, Any]]      # floor — never None after a successful fetch
    web_findings: Optional[dict[str, Any]]  # {found, items, reason?}
    transcript: Optional[dict[str, Any]]    # {found, doc_id?, excerpts?, meeting_date?, reason?}
    score_base: Optional[dict[str, Any]]    # deterministic rubric result (D9)
    synthesis: Optional[dict[str, Any]]     # raw SynthesisOutput JSON from Agentforce
    validation_errors: list[str]
    retries: int
    replay_url: Optional[str]    # the rescue brief: /briefs/{deal_id}
    brief_path: Optional[str]    # where the brief HTML landed on disk
    story_url: Optional[str]     # StoryMyData replay (fake until Phase 2.5)
    writeback: Optional[dict[str, Any]]
    status: str  # running | published | failed_validation | failed_<node>
    fetch_org_error: Optional[str]  # why the floor gave way, when it did


def new_state(deal_id: str, account_name: str) -> RescueState:
    return RescueState(
        deal_id=deal_id,
        account_name=account_name,
        org_data=None,
        web_findings=None,
        transcript=None,
        score_base=None,
        synthesis=None,
        validation_errors=[],
        retries=0,
        replay_url=None,
        writeback=None,
        status="running",
    )
