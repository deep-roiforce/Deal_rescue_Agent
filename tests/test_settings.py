"""Settings loading -- mostly guarding the paths a new user hits first."""

from __future__ import annotations

from pathlib import Path

import pytest

from deal_rescue.settings import REPO_ROOT, Settings, ToolMode

EXAMPLE = REPO_ROOT / ".env.example"


def test_copying_env_example_does_not_break_settings(tmp_path, monkeypatch):
    """`cp .env.example .env` is step one of the runbook. It must work.

    The example ships every optional key blank so they are discoverable; a blank
    value has to mean "unset", or every enum field fails validation.
    """
    env = tmp_path / ".env"
    env.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=str(env))

    assert settings.tool_mode is ToolMode.FAKE
    for tool in ("salesforce_reads", "web_research", "agentforce", "storymydata"):
        assert settings.mode_for(tool) is ToolMode.FAKE


def test_blank_values_fall_back_to_defaults(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SF_MODE=\nSTALL_DAYS=\nSEARCH_PROVIDER=\n", encoding="utf-8")

    settings = Settings(_env_file=str(env))

    assert settings.sf_mode is None            # inherits TOOL_MODE
    assert settings.stall_days == 14           # the default, not a crash
    assert settings.search_provider == "tavily"


def test_per_tool_mode_overrides_the_global(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TOOL_MODE=fake\nSF_MODE=live\n", encoding="utf-8")

    settings = Settings(_env_file=str(env))

    assert settings.mode_for("salesforce_reads") is ToolMode.LIVE
    assert settings.mode_for("web_research") is ToolMode.FAKE


def test_a_real_bad_value_still_fails(tmp_path):
    """Blank means unset; nonsense must still be rejected."""
    env = tmp_path / ".env"
    env.write_text("SF_MODE=banana\n", encoding="utf-8")

    with pytest.raises(Exception):
        Settings(_env_file=str(env))


def test_env_example_lists_every_tool_mode():
    """Docs drift guard: each tool's mode var must be discoverable."""
    text = EXAMPLE.read_text(encoding="utf-8")

    for var in ("SF_MODE", "SF_WRITEBACK_MODE", "WEB_MODE", "TRANSCRIPT_MODE",
                "AGENTFORCE_MODE", "STORYMYDATA_MODE", "TOOL_MODE"):
        assert f"{var}=" in text, f"{var} missing from .env.example"


def test_repo_root_resolves_to_the_project(tmp_path):
    assert (Path(REPO_ROOT) / "pyproject.toml").exists()
