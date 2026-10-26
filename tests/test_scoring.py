"""Rubric arithmetic and, more importantly, the signals it emits."""

from __future__ import annotations

import copy

from deal_rescue.scoring import (
    activity_slope_is_negative,
    compute_base_score,
    count_close_date_pushes,
    days_silent,
    final_score,
    find_stage_regressions,
    stall_rank,
)
from deal_rescue.settings import ScoreWeights
from tests.conftest import DEMO_DATE


def test_meridian_base_is_forty(org_data):
    breakdown = compute_base_score(org_data, DEMO_DATE)

    assert breakdown.days_silent == 19
    assert breakdown.close_date_pushes == 2
    assert len(breakdown.stage_regressions) == 1
    assert breakdown.activity_slope_negative is True
    # 100 - 19 - (2 x 8) - (1 x 15) - 10
    assert breakdown.base == 40


def test_meridian_signals_are_specific(org_data):
    signals = compute_base_score(org_data, DEMO_DATE).signals

    assert signals == [
        "19 days silent",
        "2 close-date pushes",
        "stage regression: Negotiation → Proposal on 2026-08-22",
        "declining activity over trailing 60 days",
    ]


def test_close_date_pull_in_is_not_a_push(org_data):
    pulled_in = copy.deepcopy(org_data)
    for change in pulled_in["stage_history"]:
        if change["field"] == "CloseDate":
            change["old_value"], change["new_value"] = change["new_value"], change["old_value"]

    assert count_close_date_pushes(pulled_in) == 0


def test_forward_stage_moves_are_not_regressions(org_data):
    forward_only = copy.deepcopy(org_data)
    forward_only["stage_history"] = [
        c for c in forward_only["stage_history"] if c["date"] != "2026-08-22"
    ]

    regressions, unknown = find_stage_regressions(forward_only)
    assert regressions == []
    assert unknown == set()
    assert compute_base_score(forward_only, DEMO_DATE).base == 55


def test_days_silent_is_capped(org_data):
    ancient = copy.deepcopy(org_data)
    ancient["opportunity"]["last_activity_date"] = "2020-01-01"

    assert days_silent(ancient, DEMO_DATE) > 45
    # the cap, not the raw number, drives the deduction
    assert compute_base_score(ancient, DEMO_DATE).base == 100 - 45 - 16 - 15 - 10


def test_score_is_clamped_to_zero(org_data):
    heavy = copy.deepcopy(org_data)
    heavy["stage_history"] = heavy["stage_history"] * 3  # 3 regressions, 6 pushes

    assert compute_base_score(heavy, DEMO_DATE).base == 0


def test_activity_slope_flat_history_is_not_negative(org_data):
    flat = copy.deepcopy(org_data)
    flat["activities"] = [
        {"date": "2026-08-01", "type": "Email", "subject": "a"},
        {"date": "2026-09-01", "type": "Email", "subject": "b"},
    ]

    assert activity_slope_is_negative(flat, DEMO_DATE, 30) is False


def test_weights_are_configurable(org_data):
    doubled = ScoreWeights(stage_regression_weight=30.0)

    assert compute_base_score(org_data, DEMO_DATE, doubled).base == 25


def test_final_score_clamps_both_ends():
    assert final_score(40, -6) == 34
    assert final_score(5, -15) == 0
    assert final_score(95, 15) == 100


def test_stall_rank_is_amount_times_days():
    assert stall_rank(240000, 19) == 4_560_000.0
    assert stall_rank(None, 19) == 0.0


def test_unranked_stages_are_reported_not_swallowed(org_data):
    """A stage the rubric cannot place is "I don't know", not "no regression".

    Against the live org -- standard picklist, Proposal/Price Quote and
    Negotiation/Review -- the hardcoded order matched nothing and scored a deal
    that had slipped backwards as if it had not. Silent, and 15 points wrong.
    """
    import copy

    org = copy.deepcopy(org_data)
    for change in org["stage_history"]:
        if change["field"] == "StageName":
            if change["old_value"]:
                change["old_value"] += "/Review"
            if change["new_value"]:
                change["new_value"] += "/Review"

    breakdown = compute_base_score(org, DEMO_DATE)

    assert breakdown.stage_regressions == []
    assert breakdown.unknown_stages, "unrankable stages must be surfaced"


def test_org_stage_order_finds_the_regression(org_data):
    """Given the org's own picklist order, the regression is found again."""
    import copy

    org = copy.deepcopy(org_data)
    for change in org["stage_history"]:
        if change["field"] == "StageName":
            for key in ("old_value", "new_value"):
                if change[key] == "Proposal":
                    change[key] = "Proposal/Price Quote"
                elif change[key] == "Negotiation":
                    change[key] = "Negotiation/Review"

    org_order = [
        "Prospecting", "Discovery", "Qualification",
        "Proposal/Price Quote", "Negotiation/Review", "Closed Won",
    ]
    breakdown = compute_base_score(org, DEMO_DATE, stage_order=org_order)

    assert len(breakdown.stage_regressions) == 1
    assert breakdown.unknown_stages == []
    assert breakdown.base == 40
