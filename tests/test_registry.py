"""Structural guard: a tool cannot be added without its own docs and fake.

This is the test that keeps "each tool is separately developable and documented"
true six months from now.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deal_rescue.tools import REGISTRY

TOOLS_DIR = Path(__file__).resolve().parents[1] / "src" / "deal_rescue" / "tools"
REQUIRED_FILES = ("contract.py", "fake.py", "live.py", "tool.py", "README.md", "__init__.py")


@pytest.mark.parametrize("tool_name", sorted(REGISTRY))
def test_tool_has_the_standard_layout(tool_name):
    tool_dir = TOOLS_DIR / tool_name
    assert tool_dir.is_dir(), f"{tool_name} is registered but has no package"

    for filename in REQUIRED_FILES:
        assert (tool_dir / filename).exists(), f"{tool_name}/{filename} is missing"


@pytest.mark.parametrize("tool_name", sorted(REGISTRY))
def test_tool_readme_documents_its_mode_switch(tool_name):
    readme = (TOOLS_DIR / tool_name / "README.md").read_text(encoding="utf-8")

    assert "## Contract" in readme
    assert "## Modes" in readme
    assert "## Tests" in readme


@pytest.mark.parametrize("tool_name", sorted(REGISTRY))
def test_tool_exposes_get_tool(tool_name, settings):
    module = __import__(f"deal_rescue.tools.{tool_name}", fromlist=["get_tool", "TOOL_NAME"])

    assert module.TOOL_NAME == tool_name
    assert module.get_tool(settings) is not None


def test_every_tool_package_is_registered():
    packages = {
        path.name
        for path in TOOLS_DIR.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }

    assert packages == set(REGISTRY)


def test_degradation_policy_matches_the_decisions():
    """D4: org data is the floor; web and transcript are enrichment."""
    assert REGISTRY["salesforce_reads"].degrades is False
    assert REGISTRY["web_research"].degrades is True
    assert REGISTRY["transcript"].degrades is True
    assert REGISTRY["agentforce"].degrades is False
