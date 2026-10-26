"""N6 -- synthesis via Agentforce (D5).

On a retry, `prior_errors` carries the gate's complaints back to the agent so it
can self-correct. Transport failures raise; *bad output* does not -- that is the
gate's job, not an exception (spec 4.2 N6).
"""

from __future__ import annotations

from typing import Any

from deal_rescue.settings import Settings, get_settings
from deal_rescue.tools.agentforce import SynthesisRequest, get_tool


def build_request(state: dict[str, Any]) -> SynthesisRequest:
    return SynthesisRequest(
        org_data=state.get("org_data") or {},
        web_findings=state.get("web_findings") or {"found": False, "items": []},
        transcript=state.get("transcript") or {"found": False},
        score_base=state.get("score_base") or {},
        prior_errors=list(state.get("validation_errors") or []),
    )


def synthesize(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    request = build_request(state)

    try:
        synthesis = get_tool(settings).synthesize_rescue(request)
    except Exception as exc:  # noqa: BLE001 -- transport failure ends the run
        return {
            "synthesis": None,
            "status": "failed_synthesize",
            "validation_errors": [f"synthesis transport failed: {type(exc).__name__}: {exc}"],
            "retries": int(state.get("retries", 0)) + 1,
        }

    return {"synthesis": synthesis, "retries": int(state.get("retries", 0)) + 1}
