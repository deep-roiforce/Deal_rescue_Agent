"""N1 ranking + N2 resolution."""

from __future__ import annotations

import json

import pytest

from deal_rescue.shortlist import (
    AmbiguousDeal,
    build_shortlist,
    load_shortlist,
    resolve_deal,
    save_shortlist,
    shortlist_path,
    summarize,
)
from tests.conftest import MERIDIAN_ID


def test_only_stalled_deals_are_listed(settings):
    entries = build_shortlist(settings)
    account_names = [entry.account_name for entry in entries]

    # 8 days silent -- under the 14-day threshold
    assert "Kokomo Fabricators" not in account_names
    assert all(entry.stall_days > settings.stall_days for entry in entries)


def test_risk_lane_puts_the_sickest_deal_first(settings):
    """The default lane is the rescue queue: dollars at RISK, not dollars idle.

    Exposure ranking put Northgate first on real data -- a $310K deal with a
    health score of 85, i.e. one that does not need rescuing. "Needs attention"
    for this product means decline.
    """
    entries = build_shortlist(settings)

    assert [e.rank_score for e in entries] == sorted(
        (e.rank_score for e in entries), reverse=True
    )
    assert entries[0].account_name == "Meridian Fabrication"
    assert entries[0].base_score < entries[1].base_score or (
        entries[0].rank_score > entries[1].rank_score
    )


def test_exposure_lane_is_still_available(settings, monkeypatch):
    """Which deals "need attention" differs by customer, so the other lane
    stays a setting rather than being deleted. Attention modifiers are
    neutralized here -- this test pins the LANE arithmetic alone."""
    monkeypatch.setattr("deal_rescue.shortlist.CLOSE_SOON_BOOST", 1.0)
    monkeypatch.setattr("deal_rescue.shortlist.CLOSE_NEAR_BOOST", 1.0)
    settings.shortlist_ranking = "exposure"
    entries = build_shortlist(settings)

    # $310K x 15d = 4.65M beats $240K x 19d = 4.56M
    assert entries[0].account_name == "Northgate Stamping"


def test_unknown_ranking_lane_is_rejected(settings):
    import pytest as _pytest

    settings.shortlist_ranking = "vibes"
    with _pytest.raises(ValueError):
        build_shortlist(settings)


def test_shortlist_is_capped(settings):
    settings.shortlist_n = 2
    assert len(build_shortlist(settings)) == 2


def test_entries_carry_a_deterministic_score(settings):
    meridian = next(e for e in build_shortlist(settings) if e.deal_id == MERIDIAN_ID)

    assert meridian.base_score == 40
    assert "19 days silent" in meridian.signals


def test_persisted_shortlist_round_trips(settings):
    save_shortlist(build_shortlist(settings), settings)
    path = shortlist_path(settings)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["as_of"] == "2026-09-20"
    assert len(payload["entries"]) == len(load_shortlist(settings))


def test_load_builds_the_shortlist_on_first_call(settings):
    assert not shortlist_path(settings).exists()
    assert load_shortlist(settings)
    assert shortlist_path(settings).exists()


def test_summary_is_human_readable(settings):
    text = summarize([e.as_dict() for e in build_shortlist(settings)])

    assert text.startswith("5 deals need review:")
    assert "Meridian Fabrication" in text
    assert "19d silent" in text


def test_resolve_by_partial_account_name(settings):
    assert resolve_deal("meridian", settings)["deal_id"] == MERIDIAN_ID
    assert resolve_deal("run Meridian", settings)["deal_id"] == MERIDIAN_ID


def test_resolve_by_opportunity_name(settings):
    assert resolve_deal("quoting system", settings)["deal_id"] == MERIDIAN_ID


def test_unmatchable_query_returns_candidates(settings):
    with pytest.raises(AmbiguousDeal) as excinfo:
        resolve_deal("zzzzzzzz", settings)

    assert excinfo.value.candidates  # the API turns these into a 400 body
