"""N1 `load_shortlist` + N2 deal resolution.

Deliberately *outside* the rescue graph: the shortlist is a daily batch job, the
rescue is an on-demand run against one deal a human picked (D1, D2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from deal_rescue.scoring import compute_base_score, rank_deal
from deal_rescue.settings import Settings, get_settings
from deal_rescue.tools.salesforce_reads import get_tool

SHORTLIST_FILE = "shortlist.json"

# --- attention modifiers on the lane rank (D12: constants, no UI) -------------
# Time pressure: a stalled deal closing soon outranks an equal one closing
# next quarter. Past-due counts as "soon" -- it is the most urgent of all.
CLOSE_SOON_DAYS, CLOSE_SOON_BOOST = 7, 1.5
CLOSE_NEAR_DAYS, CLOSE_NEAR_BOOST = 30, 1.25
# Worked-recently decay: a deal with a PUBLISHED rescue sinks for a few days
# so unworked carryover floats. A failed run never decays -- it still needs
# someone's attention.
RESCUED_TODAY_DECAY = 0.25           # published within the last day
RESCUED_RECENT_DAYS, RESCUED_RECENT_DECAY = 3, 0.5


def close_urgency(close_in_days: int | None) -> float:
    if close_in_days is None:
        return 1.0
    if close_in_days <= CLOSE_SOON_DAYS:  # includes past-due (negative)
        return CLOSE_SOON_BOOST
    if close_in_days <= CLOSE_NEAR_DAYS:
        return CLOSE_NEAR_BOOST
    return 1.0


def rescue_decay(days_since_rescue: int | None, last_status: str | None) -> float:
    if days_since_rescue is None or last_status != "published":
        return 1.0
    if days_since_rescue <= 1:
        return RESCUED_TODAY_DECAY
    if days_since_rescue <= RESCUED_RECENT_DAYS:
        return RESCUED_RECENT_DECAY
    return 1.0


def _days_since(ts: str | None, as_of: date) -> int | None:
    """Days between a run-log timestamp and the (possibly frozen) demo clock.

    A run stamped after `as_of` -- normal when AS_OF pins a demo date -- counts
    as worked today, never as negative days."""
    if not ts:
        return None
    try:
        run_date = datetime.fromisoformat(ts).date()
    except ValueError:
        return None
    return max(0, (as_of - run_date).days)


@dataclass
class ShortlistEntry:
    deal_id: str
    account_name: str
    opportunity_name: str
    amount: float
    stage: str
    stall_days: int
    rank_score: float
    base_score: int
    signals: list[str] = field(default_factory=list)
    # time pressure (#3) and worked-state from the run log (#1)
    close_date: str | None = None
    close_in_days: int | None = None
    days_since_rescue: int | None = None   # None = never worked
    last_rescue_status: str | None = None
    last_rescue_score: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "deal_id": self.deal_id,
            "account_name": self.account_name,
            "opportunity_name": self.opportunity_name,
            "amount": self.amount,
            "stage": self.stage,
            "stall_days": self.stall_days,
            "rank_score": self.rank_score,
            "base_score": self.base_score,
            "signals": self.signals,
            "close_date": self.close_date,
            "close_in_days": self.close_in_days,
            "days_since_rescue": self.days_since_rescue,
            "last_rescue_status": self.last_rescue_status,
            "last_rescue_score": self.last_rescue_score,
        }


def build_shortlist(settings: Settings | None = None) -> list[ShortlistEntry]:
    """Query stalled deals, score deterministically, rank by the configured
    lane -- then weight by time pressure and sink deals already worked."""
    from deal_rescue import runlog

    settings = settings or get_settings()
    as_of: date = settings.today()
    tool = get_tool(settings)
    worked = runlog.last_rescues(settings)

    entries: list[ShortlistEntry] = []
    for opp in tool.list_stalled_opportunities(settings.stall_days, as_of):
        stall_days = (as_of - opp.last_activity_date).days if opp.last_activity_date else 0
        org_data = tool.fetch_org_data(opp.id).as_state()
        breakdown = compute_base_score(
            org_data, as_of, settings.score, settings.stage_order()
        )

        close_in_days = (opp.close_date - as_of).days if opp.close_date else None
        last = worked.get(opp.id) or {}
        days_since = _days_since(last.get("ts"), as_of)

        lane_rank = rank_deal(
            settings.shortlist_ranking, opp.amount, stall_days, breakdown.base
        )
        entries.append(
            ShortlistEntry(
                deal_id=opp.id,
                account_name=opp.account_name,
                opportunity_name=opp.name,
                amount=float(opp.amount or 0),
                stage=opp.stage,
                stall_days=stall_days,
                rank_score=lane_rank
                * close_urgency(close_in_days)
                * rescue_decay(days_since, last.get("status")),
                base_score=breakdown.base,
                signals=breakdown.signals,
                close_date=opp.close_date.isoformat() if opp.close_date else None,
                close_in_days=close_in_days,
                days_since_rescue=days_since,
                last_rescue_status=last.get("status"),
                last_rescue_score=last.get("score"),
            )
        )

    entries.sort(key=lambda e: e.rank_score, reverse=True)
    return entries[: settings.shortlist_n]


def shortlist_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.state_dir) / SHORTLIST_FILE


def save_shortlist(
    entries: list[ShortlistEntry], settings: Settings | None = None
) -> Path:
    settings = settings or get_settings()
    path = shortlist_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": settings.today().isoformat(),
                "stall_days": settings.stall_days,
                "entries": [entry.as_dict() for entry in entries],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def load_shortlist(settings: Settings | None = None) -> list[dict[str, Any]]:
    """Cached shortlist, rebuilt on demand if it was never written."""
    settings = settings or get_settings()
    path = shortlist_path(settings)
    if not path.exists():
        save_shortlist(build_shortlist(settings), settings)
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def summarize(entries: list[dict[str, Any]]) -> str:
    """Human-readable line for the conversational surface."""
    if not entries:
        return "No stalled deals need review."
    lines = [f"{len(entries)} deals need review:"]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"{index}. {entry['account_name']} - {entry['opportunity_name']} "
            f"(${entry['amount']:,.0f}, {entry['stall_days']}d silent, score {entry['base_score']})"
        )
    return "\n".join(lines)


# --- N2: resolve a human's phrase to a deal --------------------------------
class AmbiguousDeal(ValueError):
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        super().__init__("ambiguous deal query")
        self.candidates = candidates


def _similarity(query: str, text: str) -> float:
    query, text = query.lower().strip(), text.lower()
    if query in text:
        return 1.0
    return SequenceMatcher(None, query, text).ratio()


def resolve_deal(query: str, settings: Settings | None = None) -> dict[str, Any]:
    """Fuzzy-match "run meridian" against the shortlist. Raises AmbiguousDeal
    when more than one entry matches well enough to be a coin flip."""
    entries = load_shortlist(settings)
    scored = [
        (
            max(
                _similarity(query, entry["account_name"]),
                _similarity(query, entry["opportunity_name"]),
            ),
            entry,
        )
        for entry in entries
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if not scored or scored[0][0] < 0.5:
        raise AmbiguousDeal([entry for _, entry in scored])

    best_score = scored[0][0]
    tied = [entry for score, entry in scored if best_score - score < 0.05]
    if len(tied) > 1:
        raise AmbiguousDeal(tied)

    return scored[0][1]
