"""Live synthesis backends.

Two providers behind the same contract (amended D5 -- docs/decisions.md):

* **LiveAnthropicSynthesis** -- Claude via the Anthropic API. The default.
  INSTRUCTIONS goes in the (cached) system prompt; the grounded INPUT payload is
  the user message; the reply is parsed with `extract_json()` and judged by the
  validation gate exactly like any other backend.
* **LiveAgentforce** -- the original Phase 2.4 design: a small MCP server
  exposing ONE tool, `synthesize_rescue(...)`, that invokes the Agentforce
  agent whose prompt template lives in `prompt.py`. Transport not wired yet.

The prompt, the merge fields and the gate are identical either way -- the
provider is only the transport for judgment.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deal_rescue.settings import Settings
from deal_rescue.tools.agentforce.contract import SynthesisRequest
from deal_rescue.tools.agentforce.prompt import (
    INSTRUCTIONS,
    build_merge_fields,
    render_input_message,
    render_user_message,
)
from deal_rescue.tools.base import ToolNotImplemented, ToolUnavailable

MCP_TOOL_NAME = "synthesize_rescue"

_FENCE = re.compile(r"```(?:json)?\s*(?P<body>\{.*?\})\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """Pull the JSON object out of an agent reply.

    Agents wrap output in prose or code fences more often than anyone admits.
    Returns None when nothing parses -- the caller turns that into a validation
    failure, never an exception (spec 4.2 N6).
    """
    if not text:
        return None

    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group("body"))

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class LiveAnthropicSynthesis:
    """Claude as the judgment layer (SYNTHESIS_PROVIDER=anthropic).

    One `messages.create` per attempt. No tools, no agent loop -- the payload is
    self-contained and the model's only job is to return the one JSON object the
    gate will check. Server-side refusal fallback is enabled so a safety-
    classifier decline reroutes inside the same call instead of failing the run.
    """

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        if client is not None:
            self.client = client
            return
        if not settings.anthropic_api_key:
            raise ToolUnavailable(
                "ANTHROPIC_API_KEY is not set -- add it to .env "
                "(or set SYNTHESIS_PROVIDER=agentforce / AGENTFORCE_MODE=fake)"
            )
        try:
            import anthropic
        except ImportError as exc:
            raise ToolUnavailable(
                'the anthropic SDK is not installed -- pip install -e ".[synthesis]"'
            ) from exc
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def synthesize_rescue(self, request: SynthesisRequest) -> dict[str, Any]:
        response = self.client.beta.messages.create(
            model=self.settings.synthesis_model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            # INSTRUCTIONS never changes between requests; cache it so retries
            # and back-to-back rescues pay for it once.
            system=[{
                "type": "text",
                "text": INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": render_input_message(request)}],
        )
        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", None) or "no detail"
            raise ToolUnavailable(f"the model declined this request ({detail})")

        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        parsed = extract_json(raw_text)
        # Malformed output is a validation failure, not an exception (N6).
        return parsed if parsed is not None else {"_raw": raw_text}


class LiveAgentforce:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not (settings.agentforce_mcp_url or settings.agentforce_api_url):
            raise ToolNotImplemented("AGENTFORCE_MCP_URL / AGENTFORCE_API_URL not set")

    def _call_mcp(self, payload: dict[str, Any]) -> str:
        raise ToolNotImplemented(
            f"MCP tool '{MCP_TOOL_NAME}' not wired yet (Phase 2.4). "
            "Stand up the wrapper server, then call it with langchain_mcp_adapters."
        )

    def synthesize_rescue(self, request: SynthesisRequest) -> dict[str, Any]:
        payload = {
            "merge_fields": build_merge_fields(request),
            "message": render_user_message(request),
            "agent_id": self.settings.agentforce_agent_id,
        }
        raw_text = self._call_mcp(payload)
        parsed = extract_json(raw_text)
        # Malformed output is a validation failure, not an exception (N6).
        return parsed if parsed is not None else {"_raw": raw_text}
