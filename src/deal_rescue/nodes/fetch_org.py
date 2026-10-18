"""N3 -- parallel branch 1: org reads. The reliability floor (D4).

This node MAY fail the run. Without CRM data there is nothing to synthesize, so
`assemble` routes a missing `org_data` straight to END.
"""

from __future__ import annotations

from typing import Any

from deal_rescue.settings import Settings, get_settings
from deal_rescue.tools.salesforce_reads import get_tool


def fetch_org(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        org_data = get_tool(settings).fetch_org_data(state["deal_id"]).as_state()
    except Exception as exc:  # noqa: BLE001 -- turned into a routed failure, not a crash
        return {
            "org_data": None,
            "status": "failed_fetch_org",
            "fetch_org_error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "org_data": org_data,
        "account_name": org_data["opportunity"]["account_name"],
    }
