"""Shortlist attention modifiers: time pressure (#3) and worked-state (#1)."""

from __future__ import annotations

from deal_rescue import runlog
from deal_rescue.shortlist import build_shortlist, close_urgency, rescue_decay


def test_closing_soon_boosts_and_past_due_is_most_urgent():
    assert close_urgency(None) == 1.0
    assert close_urgency(90) == 1.0
    assert close_urgency(30) == 1.25
    assert close_urgency(7) == 1.5
    assert close_urgency(-5) == 1.5, "past-due is the most urgent of all"


def test_only_a_published_rescue_decays():
    assert rescue_decay(None, None) == 1.0, "never worked -> full attention"
    assert rescue_decay(0, "published") == 0.25
    assert rescue_decay(3, "published") == 0.5
    assert rescue_decay(10, "published") == 1.0, "old work wears off"
    assert rescue_decay(0, "failed_validation") == 1.0, "a failed run still needs eyes"


def test_a_published_rescue_sinks_the_deal(settings):
    before = build_shortlist(settings)
    top = before[0]

    runlog.record_rescue(
        {"deal_id": top.deal_id, "account_name": top.account_name,
         "status": "published", "retries": 1,
         "synthesis": {"deal_score": {"value": 70}, "email_draft": {}}},
        settings, seconds=20.0,
    )
    after = build_shortlist(settings)

    reranked = next(e for e in after if e.deal_id == top.deal_id)
    assert reranked.days_since_rescue == 0
    assert reranked.last_rescue_status == "published"
    assert reranked.last_rescue_score == 70
    assert reranked.rank_score < top.rank_score, "worked deals sink"
    assert after[0].deal_id != top.deal_id or len(after) == 1


def test_unworked_deals_carry_the_flag(settings):
    entries = build_shortlist(settings)

    assert all(e.days_since_rescue is None for e in entries), "no run log yet"
    assert all("close_in_days" in e.as_dict() for e in entries)
