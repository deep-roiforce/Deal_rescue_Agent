from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from deal_rescue.nodes import (
    assemble,
    fetch_org,
    fetch_transcript,
    fetch_web,
    publish,
    route_after_assemble,
    route_after_validate,
    synthesize,
    validate,
)
from deal_rescue.settings import REPO_ROOT, Settings, ToolMode
from deal_rescue.state import new_state

DEMO_DATE = date(2026, 9, 20)
MERIDIAN_ID = "006MER0000000001"
MERIDIAN_ACCOUNT = "Meridian Fabrication"
FILLER_ID = "006FIL0000000003"
FILLER_ACCOUNT = "Wabash Tool & Die"


@pytest.fixture
def fixtures_dir() -> Path:
    return REPO_ROOT / "fixtures"


@pytest.fixture
def settings(tmp_path: Path, fixtures_dir: Path) -> Settings:
    """Fixture-backed settings with a deterministic 'today' and a throwaway
    state dir, so tests never touch the repo's .runs/."""
    return Settings(
        _env_file=None,
        tool_mode=ToolMode.FAKE,
        as_of=DEMO_DATE,
        state_dir=tmp_path / "runs",
        fixtures_dir=fixtures_dir,
        credentials_dir=tmp_path / "credentials",
    )


@pytest.fixture
def org_data(settings: Settings) -> dict[str, Any]:
    from deal_rescue.tools.salesforce_reads import get_tool

    return get_tool(settings).fetch_org_data(MERIDIAN_ID).as_state()


@pytest.fixture
def golden(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads(
        (fixtures_dir / "meridian" / "synthesis_golden.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def run_pipeline():
    """Drive the node functions through the same topology `graph.py` wires up.

    Kept dependency-free on purpose: the honesty rules must be testable without
    installing LangGraph. `tests/test_graph.py` checks the real graph when the
    extra is present.
    """

    def _run(settings: Settings, deal_id: str, account_name: str) -> dict[str, Any]:
        state: dict[str, Any] = dict(new_state(deal_id, account_name))

        state.update(fetch_org(state, settings))
        state.update(fetch_web(state, settings))
        state.update(fetch_transcript(state, settings))
        state.update(assemble(state, settings))
        if route_after_assemble(state) == "end":
            return state

        while True:
            state.update(synthesize(state, settings))
            state.update(validate(state, settings))
            route = route_after_validate(state, settings)
            if route == "synthesize":
                continue
            if route == "end":
                return state
            state.update(publish(state, settings))
            return state

    return _run
