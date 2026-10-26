"""SynthesisOutput -> StoryMyData request (the "engine wins" adapter).

Two decisions worth knowing:

1. **The driving metric is stage progress, not amount.** A rescue deal's amount
   is usually flat across its whole history, which renders as a straight line.
   Stage ordinal moves -- including *backwards* on a regression -- so the
   animation shows the actual story. Amount rides along as the second column.

2. **Milestones carry `rowIndex`.** Every stage change in one deal shares a
   year, so the engine's year-based anchoring would spread them evenly instead
   of landing them where they happened. `anchorLong()` in Story-engine already
   supports exact `rowIndex` placement for precisely this case; external and
   meeting milestones get a fractional index interpolated between the stage rows
   that surround them in time.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from deal_rescue.scoring import STAGE_ORDER
from deal_rescue.tools.storymydata.contract import StoryMilestone, StoryRequest

TABLE_HEADER = "Period\tStage progress\tAmount"

_TYPE_PREFIX = {
    "stage": "CRM",
    "external": "Outside signal",
    "meeting": "Meeting",
}


def _d(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def stage_ordinal(stage: str | None) -> int:
    if stage in STAGE_ORDER:
        return STAGE_ORDER.index(stage) + 1
    return 1


def build_table(table_data: list[dict[str, Any]]) -> str:
    """TSV the engine re-parses with its own deterministic numeric parser."""
    lines = [TABLE_HEADER]
    for row in table_data:
        amount = row.get("amount")
        amount_text = f"${amount:,.0f}" if amount is not None else ""
        lines.append(f"{row['date']}\t{stage_ordinal(row.get('stage'))}\t{amount_text}")
    return "\n".join(lines)


def row_index_for(target: str, row_dates: list[str]) -> float | None:
    """Float row position for a milestone date, interpolated between rows."""
    if not row_dates:
        return None
    dates = [_d(value) for value in row_dates]
    when = _d(target)

    for index, row_date in enumerate(dates):
        if when == row_date:
            return float(index)

    if when < dates[0]:
        return 0.0
    if when > dates[-1]:
        return float(len(dates) - 1)

    for index in range(len(dates) - 1):
        left, right = dates[index], dates[index + 1]
        if left < when < right:
            span = (right - left).days or 1
            return round(index + (when - left).days / span, 3)
    return None


def milestone_desc(milestone: dict[str, Any]) -> str:
    """Sub-label shown under the marker: where this moment came from."""
    prefix = _TYPE_PREFIX.get(milestone.get("type", ""), "Event")
    return f"{prefix} - {milestone['date']}"


def synthesis_to_story_request(
    synthesis: dict[str, Any],
    org_data: dict[str, Any],
    *,
    template: str = "horse-rider",
) -> StoryRequest:
    table_data = synthesis["table_data"]
    row_dates = [row["date"] for row in table_data]
    opp = org_data.get("opportunity", {})

    milestones = [
        StoryMilestone(
            period=m["date"],
            title=m["label"][:120],
            desc=milestone_desc(m)[:300],
            row_index=row_index_for(m["date"], row_dates),
        )
        for m in synthesis["milestones"]
    ]

    return StoryRequest(
        table=build_table(table_data),
        description=f"{opp.get('account_name', '')} - {opp.get('name', '')}".strip(" -"),
        milestones=milestones,
        shape="long",
        template=template,
    )
