"""N7 -- the schema gate (D7).

Pass -> publish. Fail with retries left -> back to synthesize with the errors
attached. Fail at the limit -> END with `status="failed_validation"`.

A run that ends here is a *successful* outcome of the design: it means the
pipeline refused to publish something it could not ground.
"""

from __future__ import annotations

from typing import Any

from deal_rescue.nodes.synthesize import build_request
from deal_rescue.settings import Settings, get_settings
from deal_rescue.validation import validate_synthesis


def validate(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()

    if state.get("status") == "failed_synthesize":
        return {}

    errors = validate_synthesis(state.get("synthesis"), build_request(state), settings.score)
    if not errors:
        return {"validation_errors": []}

    retries = int(state.get("retries", 0))
    exhausted = retries > settings.max_synth_retries
    return {
        "validation_errors": errors,
        "status": "failed_validation" if exhausted else state.get("status", "running"),
    }


def route_after_validate(state: dict[str, Any], settings: Settings | None = None) -> str:
    """-> 'publish' | 'synthesize' | 'end'"""
    settings = settings or get_settings()

    if state.get("status") in ("failed_synthesize", "failed_validation"):
        return "end"
    if not state.get("validation_errors"):
        return "publish"
    if int(state.get("retries", 0)) > settings.max_synth_retries:
        return "end"
    return "synthesize"
