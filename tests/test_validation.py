"""The honesty rules. These are the tests that matter (spec 10).

Each one asserts that a *specific* way of being wrong is caught -- not that the
arithmetic works.
"""

from __future__ import annotations

import copy

import pytest

from deal_rescue.nodes import assemble, fetch_org, fetch_transcript, fetch_web
from deal_rescue.nodes.synthesize import build_request
from deal_rescue.settings import Settings
from deal_rescue.state import new_state
from deal_rescue.validation import amounts_in_text, validate_synthesis
from tests.conftest import FILLER_ACCOUNT, FILLER_ID, MERIDIAN_ACCOUNT, MERIDIAN_ID


def _request(settings: Settings, deal_id: str, account_name: str):
    state = dict(new_state(deal_id, account_name))
    state.update(fetch_org(state, settings))
    state.update(fetch_web(state, settings))
    state.update(fetch_transcript(state, settings))
    state.update(assemble(state, settings))
    return build_request(state)


@pytest.fixture
def request_full(settings):
    return _request(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)


@pytest.fixture
def request_thin(settings):
    return _request(settings, FILLER_ID, FILLER_ACCOUNT)


def test_golden_record_passes(golden, request_full):
    assert validate_synthesis(golden, request_full) == []


def test_non_object_is_rejected(request_full):
    assert validate_synthesis("not json", request_full) == ["synthesis is not a JSON object"]
    assert validate_synthesis(None, request_full) == ["synthesis is not a JSON object"]


def test_unknown_field_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["confidence"] = 0.9

    errors = validate_synthesis(broken, request_full)
    assert any("confidence" in err for err in errors)


def test_invented_external_date_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["milestones"].append(
        {"date": "2026-08-05", "label": "Budget approved internally", "type": "external"}
    )

    errors = validate_synthesis(broken, request_full)
    assert any("matches no web finding" in err for err in errors)


def test_invented_stage_date_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["milestones"][0]["date"] = "2026-03-05"  # one day off

    errors = validate_synthesis(broken, request_full)
    assert any("not in the opportunity stage history" in err for err in errors)


def test_meeting_without_a_meeting_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["milestones"][2]["date"] = "2026-07-15"

    errors = validate_synthesis(broken, request_full)
    assert any("matches no logged meeting" in err for err in errors)


def test_invented_amount_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["milestones"][0]["value"] = 250000

    errors = validate_synthesis(broken, request_full)
    assert any("is not an amount in the org record" in err for err in errors)


def test_tampered_table_data_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["table_data"][1]["amount"] = 260000

    errors = validate_synthesis(broken, request_full)
    assert any("does not match the opportunity stage history" in err for err in errors)


def test_dropped_table_row_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["table_data"] = broken["table_data"][:-1]  # hide the regression

    errors = validate_synthesis(broken, request_full)
    assert any("does not match the opportunity stage history" in err for err in errors)


def test_email_to_a_stranger_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["email_draft"]["to_contact_id"] = "003NOTACONTACT01"

    errors = validate_synthesis(broken, request_full)
    assert any("is not a contact role" in err for err in errors)


def test_invented_amount_in_the_email_body_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["email_draft"]["body"] = broken["email_draft"]["body"].replace("$240K", "$310K")

    errors = validate_synthesis(broken, request_full)
    assert any("email_draft.body cites" in err for err in errors)


def test_a_single_dollar_misquote_is_rejected(golden, request_full):
    """The gate's tolerance for a wrong amount is exactly zero -- $240,001 is as
    rejected as $10M would be."""
    broken = copy.deepcopy(golden)
    broken["email_draft"]["body"] = broken["email_draft"]["body"].replace("$240K", "$240,001")

    errors = validate_synthesis(broken, request_full)
    assert any("email_draft.body cites $240,001" in err for err in errors)


def test_a_date_off_by_one_day_is_rejected(golden, request_full):
    """Same zero tolerance for dates: a milestone shifted by one day matches
    nothing that was fetched."""
    import datetime

    broken = copy.deepcopy(golden)
    milestone = next(m for m in broken["milestones"] if m["type"] == "stage")
    shifted = datetime.date.fromisoformat(milestone["date"]) + datetime.timedelta(days=1)
    milestone["date"] = shifted.isoformat()

    errors = validate_synthesis(broken, request_full)
    assert any(f"stage date {shifted.isoformat()} is not in" in err for err in errors)


def test_invented_amount_in_the_rescue_report_is_rejected(golden, request_full):
    """Prompt rule 8's matching check: report prose gets the email-body bar."""
    broken = copy.deepcopy(golden)
    broken["rescue_report"] = broken["rescue_report"] + "\nBudget approved at $1,200,000."

    errors = validate_synthesis(broken, request_full)
    assert any("rescue_report cites" in err for err in errors)


def test_missing_rescue_report_is_a_schema_error(golden, request_full):
    broken = copy.deepcopy(golden)
    del broken["rescue_report"]

    errors = validate_synthesis(broken, request_full)
    assert any("rescue_report" in err and "schema" in err for err in errors)


def test_invented_source_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["sources"].append("web:linkedin_scrape_2026-08-20")

    errors = validate_synthesis(broken, request_full)
    assert any("was not among the inputs provided" in err for err in errors)


def test_adjustment_beyond_the_bound_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["deal_score"]["llm_adjustment"] = -25
    broken["deal_score"]["value"] = 15

    errors = validate_synthesis(broken, request_full)
    assert any("exceeds the allowed" in err for err in errors)


def test_uncited_adjustment_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["deal_score"]["signals"] = request_full.score_base["signals"]

    errors = validate_synthesis(broken, request_full)
    assert any("no signal was added to justify it" in err for err in errors)


def test_dropped_deterministic_signal_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["deal_score"]["signals"] = broken["deal_score"]["signals"][1:]

    errors = validate_synthesis(broken, request_full)
    assert any("must start with the deterministic signals" in err for err in errors)


def test_rewritten_base_score_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["deal_score"]["base_deterministic"] = 60
    broken["deal_score"]["value"] = 54

    errors = validate_synthesis(broken, request_full)
    assert any("must equal the computed rubric base" in err for err in errors)


def test_arithmetic_that_does_not_add_up_is_rejected(golden, request_full):
    broken = copy.deepcopy(golden)
    broken["deal_score"]["value"] = 50

    errors = validate_synthesis(broken, request_full)
    assert any("must equal base + adjustment" in err for err in errors)


def test_claiming_full_evidence_without_evidence_is_rejected(golden, request_thin):
    """The thin-evidence rule, from the wrong direction (D11)."""
    assert request_thin.evidence_level == "org_only"

    errors = validate_synthesis(golden, request_thin)
    assert any("evidence_level must be 'org_only'" in err for err in errors)


def test_org_only_requires_the_low_context_flag(settings, request_thin):
    from deal_rescue.tools.agentforce.fake import FakeAgentforce

    output = FakeAgentforce(settings.fixtures_dir).synthesize_rescue(request_thin)
    assert validate_synthesis(output, request_thin) == []

    output["email_draft"]["low_context_flag"] = False
    errors = validate_synthesis(output, request_thin)
    assert any("low_context_flag must be true" in err for err in errors)


def test_org_only_email_must_stay_short(settings, request_thin):
    from deal_rescue.tools.agentforce.fake import FakeAgentforce

    output = FakeAgentforce(settings.fixtures_dir).synthesize_rescue(request_thin)
    output["email_draft"]["body"] = "filler. " * 200

    errors = validate_synthesis(output, request_thin)
    assert any("no confident filler" in err for err in errors)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("worth $240K", [240000.0]),
        ("worth $240,000 total", [240000.0]),
        ("a $1.2M program", [1200000.0]),
        ("no money here", []),
    ],
)
def test_currency_detection(text, expected):
    assert amounts_in_text(text) == expected


def test_emailing_the_departed_champion_is_rejected(golden, request_full):
    """Found live, on the dashboard's first run: the agent emailed Dana --
    citing her own departure announcement to her -- and the gate passed it,
    because the org has no departed flag and Dana is still a contact role.
    The people-change finding is the tell, and now the gate reads it."""
    broken = copy.deepcopy(golden)
    broken["email_draft"]["to_contact_id"] = "003MER0000000001"  # Dana
    broken["email_draft"]["to_name"] = "Dana Kowalski"

    errors = validate_synthesis(broken, request_full)
    assert any("Dana Kowalski" in err and "inactive" in err for err in errors) or any(
        "moved on" in err for err in errors
    )


def test_people_change_alone_blocks_a_recipient(golden, request_full):
    """Even when the org says active=True (it always does, live), a
    people-change finding naming the recipient is enough to reject."""
    broken = copy.deepcopy(golden)
    broken["email_draft"]["to_contact_id"] = "003MER0000000001"
    for contact in request_full.org_data["contact_roles"]:
        contact["active"] = True  # the live-org shape

    errors = validate_synthesis(broken, request_full)
    assert any("moved on" in err and "people_change" in err for err in errors)
