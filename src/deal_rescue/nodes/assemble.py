"""Fan-in. Runs once all three fetchers have reported.

Two jobs:

* decide whether the run can continue at all (org data is the floor, D4);
* compute the deterministic deal score (D9) so the agent receives a number it is
  only allowed to *adjust*, never author.
"""

from __future__ import annotations

from typing import Any

from deal_rescue.scoring import compute_base_score
from deal_rescue.settings import Settings, get_settings


def assemble(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    org_data = state.get("org_data")
    if not org_data:
        return {"status": state.get("status") or "failed_fetch_org"}

    breakdown = compute_base_score(
        org_data, settings.today(), settings.score, settings.stage_order()
    )
    return {"score_base": breakdown.as_dict()}


def route_after_assemble(state: dict[str, Any]) -> str:
    """-> 'synthesize' | 'end'"""
    return "synthesize" if state.get("org_data") else "end"
