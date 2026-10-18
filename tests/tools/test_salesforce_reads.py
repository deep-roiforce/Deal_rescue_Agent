from __future__ import annotations

from datetime import date

import pytest

from deal_rescue.tools.base import ToolError
from deal_rescue.tools.salesforce_reads import get_tool
from tests.conftest import DEMO_DATE, MERIDIAN_ID


def test_meridian_fixture_round_trips_through_the_contract(settings):
    org = get_tool(settings).fetch_org_data(MERIDIAN_ID)

    assert org.opportunity.amount == 240000
    assert org.opportunity.stage == "Proposal"  # after the regression
    assert org.opportunity.created_date == date(2026, 3, 4)
    assert len(org.stage_history) == 7
    assert len(org.contact_roles) == 3
    assert len(org.activities) == 8


def test_state_dict_is_json_safe(settings):
    state = get_tool(settings).fetch_org_data(MERIDIAN_ID).as_state()

    assert state["opportunity"]["created_date"] == "2026-03-04"
    assert isinstance(state["stage_history"][0]["date"], str)


def test_field_history_carries_both_stage_and_close_date_rows(settings):
    history = get_tool(settings).get_opportunity_history(MERIDIAN_ID)
    fields = [change.field for change in history]

    assert fields.count("StageName") == 5
    assert fields.count("CloseDate") == 2


def test_departed_champion_is_marked_inactive(settings):
    roles = get_tool(settings).get_contact_roles(MERIDIAN_ID)
    dana = next(role for role in roles if role.name == "Dana Kowalski")

    assert dana.role == "Champion"
    assert dana.active is False


def test_stalled_query_respects_the_threshold(settings):
    stalled = get_tool(settings).list_stalled_opportunities(14, DEMO_DATE)
    names = {opp.account_name for opp in stalled}

    assert "Meridian Fabrication" in names
    assert "Kokomo Fabricators" not in names  # 8 days silent


def test_stalled_query_is_relative_to_as_of(settings):
    assert get_tool(settings).list_stalled_opportunities(14, date(2026, 9, 6)) != (
        get_tool(settings).list_stalled_opportunities(14, DEMO_DATE)
    )


def test_filler_deals_get_synthetic_org_data(settings):
    org = get_tool(settings).fetch_org_data("006FIL0000000003")

    assert org.opportunity.account_name == "Wabash Tool & Die"
    assert len(org.stage_history) == 2
    assert org.contact_roles


def test_unknown_deal_is_fatal_not_degraded(settings):
    """org data is the floor -- this tool does not return an empty payload."""
    with pytest.raises(ToolError):
        get_tool(settings).fetch_org_data("006NOPE0000000001")


# --- live adapter mapping (pure functions, no org needed) -------------------
HISTORY_SNAPSHOTS = [
    {"StageName": "Prospecting", "Amount": 240000.0, "CloseDate": "2026-09-30",
     "CreatedDate": "2026-09-21T02:58:18.000+0000"},
    {"StageName": "Prospecting", "Amount": 240000.0, "CloseDate": "2026-07-31",
     "CreatedDate": "2026-09-21T02:58:41.000+0000"},
    {"StageName": "Qualification", "Amount": 240000.0, "CloseDate": "2026-07-31",
     "CreatedDate": "2026-09-21T02:58:45.000+0000"},
    {"StageName": "Qualification", "Amount": 240000.0, "CloseDate": "2026-08-29",
     "CreatedDate": "2026-09-21T02:58:51.000+0000"},
    {"StageName": "Negotiation/Review", "Amount": 240000.0, "CloseDate": "2026-09-30",
     "CreatedDate": "2026-09-21T02:58:57.000+0000"},
    {"StageName": "Proposal/Price Quote", "Amount": 240000.0, "CloseDate": "2026-09-30",
     "CreatedDate": "2026-09-21T02:59:12.000+0000"},
]


def test_history_snapshots_become_deltas():
    """OpportunityHistory is a snapshot per change, not a before/after pair.

    These rows are the shape the real org returned for Meridian. The contract
    wants deltas, so consecutive rows are diffed.
    """
    from deal_rescue.tools.salesforce_reads.live import history_to_changes

    changes = history_to_changes(HISTORY_SNAPSHOTS, 240000.0)
    stage_changes = [c for c in changes if c.field == "StageName"]
    close_changes = [c for c in changes if c.field == "CloseDate"]

    assert stage_changes[0].old_value is None, "first row is creation"
    assert stage_changes[0].new_value == "Prospecting"
    assert (stage_changes[-1].old_value, stage_changes[-1].new_value) == (
        "Negotiation/Review", "Proposal/Price Quote",
    ), "the regression must survive the diff"
    assert len(close_changes) == 3


def test_close_date_pushes_survive_the_mapping():
    """Two pushes and one pull-in, as seeded. The rubric counts only pushes."""
    from deal_rescue.scoring import count_close_date_pushes
    from deal_rescue.tools.salesforce_reads.live import history_to_changes

    changes = history_to_changes(HISTORY_SNAPSHOTS, 240000.0)
    org_data = {"stage_history": [c.model_dump(mode="json") for c in changes]}

    assert count_close_date_pushes(org_data) == 2


def test_empty_history_maps_to_nothing():
    from deal_rescue.tools.salesforce_reads.live import history_to_changes

    assert history_to_changes([], None) == []


def test_soql_dates_and_datetimes_both_parse():
    from deal_rescue.tools.salesforce_reads.live import as_date

    assert as_date("2026-09-30").isoformat() == "2026-09-30"
    assert as_date("2026-09-21T02:58:18.000+0000").isoformat() == "2026-09-21"
    assert as_date(None) is None
    assert as_date("") is None
