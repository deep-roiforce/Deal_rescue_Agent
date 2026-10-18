"""The Anthropic synthesis backend: prompt assembly, parsing, failure modes.

No network anywhere -- a stub client stands in for the SDK, so these tests pin
the request we send (system = INSTRUCTIONS, cached; user = INPUT payload) and
how replies and refusals are handled.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deal_rescue.settings import Settings, ToolMode
from deal_rescue.tools.agentforce.contract import SynthesisRequest
from deal_rescue.tools.agentforce.live import LiveAnthropicSynthesis
from deal_rescue.tools.agentforce.prompt import INSTRUCTIONS
from deal_rescue.tools.agentforce.tool import get_tool
from deal_rescue.tools.base import ToolUnavailable


def _settings(**overrides) -> Settings:
    defaults = dict(_env_file=None, anthropic_api_key="sk-test")
    defaults.update(overrides)
    return Settings(**defaults)


def _request(prior_errors: list[str] | None = None) -> SynthesisRequest:
    return SynthesisRequest(
        org_data={"opportunity": {"id": "006X", "account_name": "Acme", "amount": 1000.0}},
        prior_errors=prior_errors or [],
    )


class StubClient:
    """Captures the request and replies with a canned message."""

    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict] = []
        response = SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(explanation="declined for the test"),
            content=[SimpleNamespace(type="text", text=text)],
        )
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: self._record(kwargs, response))
        )

    def _record(self, kwargs, response):
        self.calls.append(kwargs)
        return response


def test_sends_instructions_as_cached_system_and_input_as_user():
    stub = StubClient('{"ok": true}')
    tool = LiveAnthropicSynthesis(_settings(), client=stub)

    tool.synthesize_rescue(_request())

    call = stub.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["system"][0]["text"] == INSTRUCTIONS
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    user = call["messages"][0]["content"]
    assert user.startswith("INPUT:")
    assert INSTRUCTIONS not in user, "instructions belong in system, not duplicated"


def test_retry_feeds_the_gate_errors_back():
    stub = StubClient('{"ok": true}')
    tool = LiveAnthropicSynthesis(_settings(), client=stub)

    tool.synthesize_rescue(_request(prior_errors=["milestone X: invented date"]))

    user = stub.calls[0]["messages"][0]["content"]
    assert "REJECTED" in user
    assert "milestone X: invented date" in user


def test_parses_json_out_of_a_fenced_reply():
    payload = {"milestones": [], "sources": []}
    stub = StubClient(f"Here you go:\n```json\n{json.dumps(payload)}\n```")
    tool = LiveAnthropicSynthesis(_settings(), client=stub)

    assert tool.synthesize_rescue(_request()) == payload


def test_unparseable_reply_becomes_a_validation_failure_not_an_exception():
    stub = StubClient("I cannot produce JSON today.")
    tool = LiveAnthropicSynthesis(_settings(), client=stub)

    output = tool.synthesize_rescue(_request())

    assert output == {"_raw": "I cannot produce JSON today."}


def test_a_refusal_raises_instead_of_retrying_forever():
    stub = StubClient("", stop_reason="refusal")
    tool = LiveAnthropicSynthesis(_settings(), client=stub)

    with pytest.raises(ToolUnavailable, match="declined"):
        tool.synthesize_rescue(_request())


def test_missing_api_key_is_a_clear_setup_error():
    with pytest.raises(ToolUnavailable, match="ANTHROPIC_API_KEY"):
        LiveAnthropicSynthesis(_settings(anthropic_api_key=None))


def test_live_mode_routes_to_anthropic_by_default():
    settings = _settings(agentforce_mode=ToolMode.LIVE)

    assert isinstance(get_tool(settings), LiveAnthropicSynthesis)


def test_model_is_configurable():
    stub = StubClient('{"ok": true}')
    tool = LiveAnthropicSynthesis(_settings(synthesis_model="claude-sonnet-5-5"), client=stub)

    tool.synthesize_rescue(_request())

    assert stub.calls[0]["model"] == "claude-sonnet-5-5"
