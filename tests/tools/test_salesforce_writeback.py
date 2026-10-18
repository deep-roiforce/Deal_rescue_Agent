from __future__ import annotations

import json

from deal_rescue.settings import Settings, ToolMode
from deal_rescue.tools.salesforce_writeback import (
    FIELD_APPROVED,
    FIELD_EVIDENCE_LEVEL,
    FIELD_EXTERNAL_ID,
    FIELD_REPLAY_URL,
    FIELD_SCORE,
    FIELD_SIGNALS,
    TASK_SUBJECT_MAX,
    DraftEmail,
    WritebackPayload,
    audit_findings_from_state,
    get_tool,
    make_run_key,
)
from deal_rescue.tools.salesforce_writeback.live import LiveSalesforceWriteback
from tests.conftest import DEMO_DATE, MERIDIAN_ID

WEB = {
    "found": True,
    "items": [
        {
            "id": "expansion_pr_2026-09-02",
            "title": "Plant 3 expansion",
            "url": "https://example.com/journal",
            "date": "2026-09-02",
            "signal_type": "expansion",
        }
    ],
}
TRANSCRIPT = {
    "found": True,
    "doc_id": "DOC123",
    "doc_title": "Review - 2026-07-14",
    "meeting_date": "2026-07-14",
}


def _payload(**overrides) -> WritebackPayload:
    defaults = dict(
        deal_id=MERIDIAN_ID,
        score=34,
        signals=["19 days silent", "champion departed (web)"],
        replay_url="https://storymydata.local/app.html#s=abc",
        email_draft=DraftEmail(
            to_contact_id="003MER0000000002",
            to_name="Ray Gutierrez",
            subject="Plant 3 and quoting",
            body="Ray, ...",
        ),
        audit_findings=audit_findings_from_state(WEB, TRANSCRIPT),
        evidence_level="full",
        run_key=make_run_key(MERIDIAN_ID, DEMO_DATE),
    )
    defaults.update(overrides)
    return WritebackPayload(**defaults)


def test_audit_findings_cover_web_and_transcript():
    findings = audit_findings_from_state(WEB, TRANSCRIPT)

    assert [f.source for f in findings] == [
        "web:expansion_pr_2026-09-02",
        "transcript:2026-07-14",
    ]


def test_transcript_finding_links_to_the_doc():
    transcript_finding = audit_findings_from_state(None, TRANSCRIPT)[0]

    assert transcript_finding.url == "https://docs.google.com/document/d/DOC123"


def test_no_evidence_means_no_audit_records():
    assert audit_findings_from_state({"found": False, "items": []}, {"found": False}) == []


def test_live_request_maps_onto_the_org_api_names():
    settings = Settings(_env_file=None, sf_mcp_url="https://example.invalid/mcp")
    request = LiveSalesforceWriteback(settings).build_request(_payload())

    fields = request["opportunity_fields"]
    assert fields[FIELD_SCORE] == 34
    assert fields[FIELD_SIGNALS] == "19 days silent\nchampion departed (web)"
    assert fields[FIELD_REPLAY_URL].endswith("#s=abc")


def test_draft_task_starts_unapproved():
    """The rep ticks the flag; a Flow sends it natively (D8)."""
    settings = Settings(_env_file=None, sf_mcp_url="https://example.invalid/mcp")
    request = LiveSalesforceWriteback(settings).build_request(_payload())

    assert request["draft_task"]["fields"][FIELD_APPROVED] is False
    assert request["draft_task"]["who_id"] == "003MER0000000002"


def test_audit_tasks_carry_their_source():
    settings = Settings(_env_file=None, sf_mcp_url="https://example.invalid/mcp")
    request = LiveSalesforceWriteback(settings).build_request(_payload())

    subjects = [task["subject"] for task in request["audit_tasks"]]
    assert subjects[0].startswith("Evidence [web:expansion_pr_2026-09-02]")
    assert "https://example.com/journal" in request["audit_tasks"][0]["description"]


def test_evidence_level_reaches_the_org():
    """A thin-evidence draft must be visible as such to the rep (D11)."""
    settings = Settings(_env_file=None, sf_mcp_url="https://example.invalid/mcp")
    tool = LiveSalesforceWriteback(settings)

    full = tool.build_request(_payload())
    thin = tool.build_request(_payload(evidence_level="org_only"))

    assert full["opportunity_fields"][FIELD_EVIDENCE_LEVEL] == "full"
    assert thin["opportunity_fields"][FIELD_EVIDENCE_LEVEL] == "org_only"


def test_draft_subject_is_truncated_to_the_salesforce_limit():
    """Task.Subject is 255; truncate before the insert, not after it fails."""
    settings = Settings(_env_file=None, sf_mcp_url="https://example.invalid/mcp")
    draft = DraftEmail(
        to_contact_id="003MER0000000002",
        to_name="Ray Gutierrez",
        subject="x" * 400,
        body="Ray, ...",
    )

    request = LiveSalesforceWriteback(settings).build_request(_payload(email_draft=draft))

    assert len(request["draft_task"]["subject"]) == TASK_SUBJECT_MAX


def test_run_key_is_stable_per_deal_per_day():
    assert make_run_key(MERIDIAN_ID, DEMO_DATE) == f"{MERIDIAN_ID}-2026-09-20"


def test_every_written_record_carries_the_run_key():
    """Re-running a rescue must upsert, not litter the deal with duplicates."""
    settings = Settings(_env_file=None, sf_mcp_url="https://example.invalid/mcp")
    request = LiveSalesforceWriteback(settings).build_request(_payload())
    run_key = make_run_key(MERIDIAN_ID, DEMO_DATE)

    assert request["run_key"] == run_key
    assert request["draft_task"]["fields"][FIELD_EXTERNAL_ID] == f"{run_key}-draft"

    external_ids = [task["fields"][FIELD_EXTERNAL_ID] for task in request["audit_tasks"]]
    assert external_ids == [
        f"{run_key}-web:expansion_pr_2026-09-02",
        f"{run_key}-transcript:2026-07-14",
    ]
    assert len(set(external_ids)) == len(external_ids)  # no collisions


def test_fake_persists_the_payload(tmp_path, fixtures_dir):
    settings = Settings(
        _env_file=None,
        tool_mode=ToolMode.FAKE,
        as_of=DEMO_DATE,
        state_dir=tmp_path,
        fixtures_dir=fixtures_dir,
    )
    result = get_tool(settings).create_rescue_writeback(_payload())

    assert result.opportunity_updated is True
    assert len(result.audit_task_ids) == 2
    assert result.draft_task_id

    saved = json.loads(
        (tmp_path / "writebacks" / f"{MERIDIAN_ID}.json").read_text(encoding="utf-8")
    )
    assert saved["score"] == 34
