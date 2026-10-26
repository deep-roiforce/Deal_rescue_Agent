"""The setup page's backend: whitelist, masking, mode flips."""

from __future__ import annotations

import pytest

from deal_rescue import envfile, setupweb
from deal_rescue.settings import Settings


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TOOL_MODE=fake\n# a comment to preserve\n", encoding="utf-8")
    monkeypatch.setattr(envfile, "ENV_PATH", path)
    return path


def test_saving_keys_writes_env_and_flips_modes(env_file):
    result = setupweb.apply_config({
        "search_api_key": "tvly-TESTKEY123",
        "anthropic_api_key": "sk-ant-TESTKEY456",
        "synthesis_model": "claude-sonnet-5-5",
    })

    text = env_file.read_text(encoding="utf-8")
    assert sorted(result["saved"]) == ["anthropic_api_key", "search_api_key", "synthesis_model"]
    assert "SEARCH_API_KEY=tvly-TESTKEY123" in text
    assert "ANTHROPIC_API_KEY=sk-ant-TESTKEY456" in text
    assert "SYNTHESIS_MODEL=claude-sonnet-5-5" in text
    assert "WEB_MODE=live" in text, "a saved key is intent to go live"
    assert "AGENTFORCE_MODE=live" in text
    assert "# a comment to preserve" in text


def test_blank_values_never_erase(env_file):
    setupweb.apply_config({"search_api_key": "tvly-FIRST000"})
    setupweb.apply_config({"search_api_key": "   "})

    assert "SEARCH_API_KEY=tvly-FIRST000" in env_file.read_text(encoding="utf-8")


def test_unknown_fields_are_rejected(env_file):
    with pytest.raises(ValueError, match="unknown setup field"):
        setupweb.apply_config({"sf_private_key_path": "/etc/passwd"})
    assert "sf_private_key_path" not in env_file.read_text(encoding="utf-8").lower()


def test_model_must_be_a_known_model(env_file):
    with pytest.raises(ValueError, match="synthesis_model must be one of"):
        setupweb.apply_config({"synthesis_model": "gpt-9"})


def test_status_masks_secrets(tmp_path):
    settings = Settings(
        _env_file=None, credentials_dir=tmp_path,
        sf_client_id="3MVG9SECRETSECRETCONSUMER",
        anthropic_api_key="sk-ant-VERYSECRETVALUE9876",
    )

    report = setupweb.status(settings)

    fields = report["fields"]
    assert fields["sf_client_id"] == {"set": True, "hint": "…UMER"}
    assert fields["anthropic_api_key"]["hint"] == "…9876"
    flattened = str(report)
    assert "VERYSECRETVALUE" not in flattened
    assert "SECRETSECRET" not in flattened
