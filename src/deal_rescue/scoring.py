"""Deterministic deal-score rubric (spec §7, D9).

The LLM never produces the base number. It may adjust within ±bound and must
cite a signal for any nonzero adjustment — `validation.py` enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from deal_rescue.settings import ScoreWeights

# Ordered pipeline. Any move to a lower index is a regression.
STAGE_ORDER = [
    "Prospecting",
    "Discovery",
    "Qualification",
    "Proposal",
    "Negotiation",
    "Closed Won",
]


def _d(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass
class ScoreBreakdown:
    base: int
    days_silent: int
    close_date_pushes: int
    stage_regressions: list[dict[str, Any]]
    activity_slope_negative: bool
    signals: list[str] = field(default_factory=list)
    deductions: dict[str, float] = field(default_factory=dict)
    unknown_stages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "days_silent": self.days_silent,
            "close_date_pushes": self.close_date_pushes,
            "stage_regressions": self.stage_regressions,
            "activity_slope_negative": self.activity_slope_negative,
            "signals": list(self.signals),
            "deductions": dict(self.deductions),
            "unknown_stages": list(self.unknown_stages),
        }


def days_silent(org_data: dict[str, Any], as_of: date) -> int:
    last = _d(org_data["opportunity"].get("last_activity_date"))
    if last is None:
        created = _d(org_data["opportunity"]["created_date"])
        last = created
    return max((as_of - last).days, 0)


def count_close_date_pushes(org_data: dict[str, Any]) -> int:
    pushes = 0
    for change in org_data.get("stage_history", []):
        if change.get("field") != "CloseDate":
            continue
        old, new = _d(change.get("old_value")), _d(change.get("new_value"))
        if old and new and new > old:
            pushes += 1
    return pushes


def find_stage_regressions(
    org_data: dict[str, Any], stage_order: list[str] | None = None
) -> tuple[list[dict[str, Any]], set[str]]:
    """Regressions, plus any stage names we could not rank.

    The unknown set is returned rather than swallowed. A stage this rubric
    cannot place is not "no regression" -- it is "I could not tell", and those
    are different answers. Against a real org using the standard picklist
    (Proposal/Price Quote, Negotiation/Review) the hardcoded order matched
    nothing and reported a clean deal that had in fact slipped backwards.
    """
    order = stage_order or STAGE_ORDER
    out: list[dict[str, Any]] = []
    unknown: set[str] = set()

    for change in org_data.get("stage_history", []):
        if change.get("field") != "StageName":
            continue
        old, new = change.get("old_value"), change.get("new_value")
        if old is None or new is None:
            continue
        for stage in (old, new):
            if stage not in order:
                unknown.add(stage)
        if old not in order or new not in order:
            continue
        if order.index(new) < order.index(old):
            out.append({"date": change["date"], "from": old, "to": new})
    return out, unknown


def activity_slope_is_negative(
    org_data: dict[str, Any], as_of: date, window_days: int
) -> bool:
    """Negative slope = fewer activities in the last `window_days` than in the
    `window_days` before that (the trailing-60d window of spec §7 read as two
    30-day halves)."""
    recent_start = as_of - timedelta(days=window_days)
    prior_start = as_of - timedelta(days=window_days * 2)

    recent = prior = 0
    for act in org_data.get("activities", []):
        d = _d(act.get("date"))
        if d is None:
            continue
        if recent_start < d <= as_of:
            recent += 1
        elif prior_start < d <= recent_start:
            prior += 1
    return recent < prior


def compute_base_score(
    org_data: dict[str, Any],
    as_of: date,
    weights: ScoreWeights | None = None,
    stage_order: list[str] | None = None,
) -> ScoreBreakdown:
    w = weights or ScoreWeights()

    silent = days_silent(org_data, as_of)
    pushes = count_close_date_pushes(org_data)
    regressions, unknown = find_stage_regressions(org_data, stage_order)
    slope_negative = activity_slope_is_negative(org_data, as_of, w.activity_slope_window_days)

    deductions = {
        "days_silent": min(silent, w.days_silent_cap) * w.days_silent_weight,
        "close_date_pushes": pushes * w.close_date_push_weight,
        "stage_regressions": len(regressions) * w.stage_regression_weight,
        "activity_slope": w.activity_slope_weight if slope_negative else 0.0,
    }
    base = int(max(0, min(100, round(w.start - sum(deductions.values())))))

    signals: list[str] = []
    if silent:
        signals.append(f"{silent} days silent")
    if pushes:
        signals.append(f"{pushes} close-date push{'es' if pushes != 1 else ''}")
    for r in regressions:
        signals.append(f"stage regression: {r['from']} → {r['to']} on {r['date']}")
    if slope_negative:
        signals.append(
            f"declining activity over trailing {w.activity_slope_window_days * 2} days"
        )

    return ScoreBreakdown(
        base=base,
        days_silent=silent,
        close_date_pushes=pushes,
        stage_regressions=regressions,
        activity_slope_negative=slope_negative,
        signals=signals,
        deductions=deductions,
        unknown_stages=sorted(unknown),
    )


def final_score(base: int, llm_adjustment: int) -> int:
    return int(max(0, min(100, base + llm_adjustment)))


def stall_rank(amount: float | None, stall_days_value: int) -> float:
    """Shortlist ranking v1 (D12): amount × stall_days."""
    return float(amount or 0) * float(stall_days_value)


def risk_rank(amount: float | None, health_score: int) -> float:
    """Dollars at risk: amount * (100 - health). The rescue lane.

    "Needs attention" is customer-specific -- it can mean at-risk or it can
    mean expanding -- and this product is Deal Rescue, so decline is what
    earns a place on the list.

    There is deliberately no stall_days term: days-silent is already one of the
    four components inside the health score, so this replaces a one-factor
    stall measure with the full rubric rather than double-counting it.
    """
    return float(amount or 0) * float(max(0, 100 - health_score))


RANKINGS = {
    "risk": "amount * (100 - health) -- the rescue queue",
    "exposure": "amount * stall_days -- pipeline hygiene, the spec's v1",
}


def rank_deal(mode: str, amount: float | None, stall_days_value: int, health: int) -> float:
    """Rank one deal in the configured lane."""
    if mode == "exposure":
        return stall_rank(amount, stall_days_value)
    if mode == "risk":
        return risk_rank(amount, health)
    raise ValueError(
        f"unknown shortlist ranking {mode!r}; expected one of {sorted(RANKINGS)}"
    )
