from __future__ import annotations

import pytest

from deal_rescue.nodes import assemble, fetch_org, fetch_transcript, fetch_web
from deal_rescue.nodes.synthesize import build_request
from deal_rescue.settings import Settings, ToolMode
from deal_rescue.state import new_state
from deal_rescue.tools.agentforce import build_merge_fields
from deal_rescue.tools.agentforce.fake import FakeAgentforce
from deal_rescue.tools.agentforce.live import extract_json
from deal_rescue.tools.agentforce.prompt import INSTRUCTIONS, allowed_sources
from deal_rescue.validation import validate_synthesis
from tests.conftest import (
    DEMO_DATE,
    FILLER_ACCOUNT,
    FILLER_ID,
    MERIDIAN_ACCOUNT,
    MERIDIAN_ID,
)


def _request(settings, deal_id, account_name):
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


def test_meridian_reproduces_the_golden_record(settings, request_full, golden):
    output = FakeAgentforce(settings.fixtures_dir).synthesize_rescue(request_full)

    assert output == golden


def test_base_score_is_regrounded_on_the_rubric(settings, request_full):
    """The fixture can never drift from scoring.py."""
    request_full.score_base["base"] = 55
    output = FakeAgentforce(settings.fixtures_dir).synthesize_rescue(request_full)

    assert output["deal_score"]["base_deterministic"] == 55
    assert output["deal_score"]["value"] == 49  # 55 - 6


def test_thin_evidence_produces_an_org_only_answer(settings, request_thin):
    output = FakeAgentforce(settings.fixtures_dir).synthesize_rescue(request_thin)

    assert output["evidence_level"] == "org_only"
    assert output["email_draft"]["low_context_flag"] is True
    assert output["deal_score"]["llm_adjustment"] == 0
    assert "$" not in output["email_draft"]["body"]
    assert validate_synthesis(output, request_thin) == []


@pytest.mark.parametrize("fault", ["invented_date", "invented_source"])
def test_faults_produce_output_the_gate_rejects(settings, request_full, fault):
    tool = FakeAgentforce(settings.fixtures_dir, fault=fault)

    bad = tool.synthesize_rescue(request_full)
    assert validate_synthesis(bad, request_full) != []


@pytest.mark.parametrize("fault", ["invented_date", "invented_source"])
def test_faults_self_correct_once_told_why(settings, request_full, fault):
    tool = FakeAgentforce(settings.fixtures_dir, fault=fault)

    errors = validate_synthesis(tool.synthesize_rescue(request_full), request_full)
    request_full.prior_errors = errors

    retried = tool.synthesize_rescue(request_full)
    assert validate_synthesis(retried, request_full) == []


def test_permanent_fault_never_self_corrects(settings, request_full):
    tool = FakeAgentforce(settings.fixtures_dir, fault="permanent")
    request_full.prior_errors = ["you invented a date"]

    assert validate_synthesis(tool.synthesize_rescue(request_full), request_full) != []


def test_mode_switch_passes_the_fault_through(tmp_path, fixtures_dir):
    settings = Settings(
        _env_file=None,
        tool_mode=ToolMode.FAKE,
        as_of=DEMO_DATE,
        state_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        agentforce_fake_fault="permanent",
    )
    from deal_rescue.tools.agentforce import get_tool

    assert get_tool(settings).fault == "permanent"


# --- grounding payload -----------------------------------------------------
def test_merge_fields_expose_only_real_dates_and_amounts(request_full):
    fields = build_merge_fields(request_full)

    assert fields["ALLOWED_AMOUNTS"] == [240000.0]
    assert fields["ALLOWED_STAGE_DATES"] == [
        "2026-03-04",
        "2026-03-28",
        "2026-04-18",
        "2026-06-10",
        "2026-08-22",
    ]
    assert fields["ALLOWED_WEB_DATES"] == [
        "2026-08-20",
        "2026-09-02",
        "2026-09-08",
    ]
    assert "2026-07-14" in fields["ALLOWED_MEETING_DATES"]
    assert fields["SCORE_BASE"] == 40


def test_allowed_sources_covers_every_input(request_full):
    sources = allowed_sources(request_full)

    assert "transcript:2026-07-14" in sources
    assert "web:expansion_pr_2026-09-02" in sources
    assert "web:linkedin_scrape_2026-08-20" not in sources


def test_thin_request_offers_no_external_sources(request_thin):
    sources = allowed_sources(request_thin)

    assert not [source for source in sources if source.startswith(("web:", "transcript:"))]


def test_instructions_encode_the_locked_rules():
    assert "NEVER invent" in INSTRUCTIONS
    assert "ALLOWED_CONTACT_IDS" in INSTRUCTIONS
    assert "org_only" in INSTRUCTIONS
    assert "You select, label and annotate. You do not compute." in INSTRUCTIONS


# --- agent reply parsing ---------------------------------------------------
def test_extract_json_handles_code_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_handles_surrounding_prose():
    assert extract_json('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_extract_json_returns_none_on_junk():
    assert extract_json("I could not complete that request.") is None
    assert extract_json("") is None


def test_grounded_fake_never_writes_to_the_departed(settings, request_full):
    """Live-org shape: nobody is marked inactive, so the people-change finding
    is the only tell. The agent must still pick Ray, not Dana."""
    for contact in request_full.org_data["contact_roles"]:
        contact["active"] = True

    output = FakeAgentforce(settings.fixtures_dir)._grounded(request_full)

    assert output["email_draft"]["to_name"] == "Ray Gutierrez"
    assert validate_synthesis(output, request_full) == []
