"""N4 -- parallel branch 2: outside-world signals.

Never raises (D4). The live adapter already degrades internally; the node
repeats the guarantee so a broken *tool* -- any tool, including one added later
-- still cannot take the run down.
"""

from __future__ import annotations

from typing import Any

from deal_rescue.settings import Settings, get_settings
from deal_rescue.tools.base import degraded
from deal_rescue.tools.web_research import get_tool


def fetch_web(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    account_name = state.get("account_name") or ""
    if not account_name:
        return {"web_findings": degraded("no account name")}

    try:
        findings = get_tool(settings).search(account_name)
    except Exception as exc:  # noqa: BLE001 -- enrichment never fails the run
        return {"web_findings": degraded(f"web research failed: {type(exc).__name__}: {exc}")}

    return {"web_findings": findings}
