"""N5 -- parallel branch 3: meeting transcript.

Never raises (D4), for the same reason as `fetch_web`.
"""

from __future__ import annotations

from typing import Any

from deal_rescue.settings import Settings, get_settings
from deal_rescue.tools.transcript import get_tool


def fetch_transcript(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    account_name = state.get("account_name") or ""
    if not account_name:
        return {"transcript": {"found": False, "reason": "no account name"}}

    try:
        result = get_tool(settings).fetch_latest(account_name, deal_id=state.get("deal_id"))
    except Exception as exc:  # noqa: BLE001 -- enrichment never fails the run
        return {
            "transcript": {
                "found": False,
                "reason": f"transcript lookup failed: {type(exc).__name__}: {exc}",
            }
        }

    return {"transcript": result}
