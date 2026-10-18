"""Shared plumbing for tools.

A *tool* is one integration with one outside system. Every tool package has the
same five files so any of them can be worked on, tested and documented in
isolation:

    contract.py   typed request/response models — the thing other code imports
    fake.py       fixture-backed implementation (Phase 1, no network)
    live.py       real adapter (Phase 2)
    tool.py       mode switch: returns fake or live per settings
    README.md     what it does, contract, how to run it live, how to test it

Nodes depend on `contract.py` + `tool.get_tool()` only — never on `fake`/`live`
directly. That is what keeps a tool swappable without touching the graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ToolError(RuntimeError):
    """A tool failed in a way the caller must handle."""


class ToolUnavailable(ToolError):
    """Soft failure: the backing service is absent/empty. Enrichment tools turn
    this into `{found: false, reason: ...}` instead of raising (D4)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ToolNotImplemented(ToolError):
    """Live adapter not built yet (Phase 2)."""


@dataclass(frozen=True)
class ToolSpec:
    """Registry metadata. Also what `docs/tools.md` and the registry test read."""

    name: str
    summary: str
    transport: str            # "mcp" | "https" | "google-api"
    node: str                 # graph node that consumes it
    degrades: bool            # True  = may return found:false, never raises (D4)
                              # False = failure is fatal to the run
    phase: str                # build phase the live adapter lands in


def degraded(reason: str) -> dict[str, Any]:
    """Uniform empty payload for enrichment tools."""
    return {"found": False, "items": [], "reason": reason}


def never_raise(reason_prefix: str) -> Callable:
    """Decorator for enrichment tools: any exception becomes a degraded result.

    D4: "External sources are enrichment, not dependencies."
    """

    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return fn(*args, **kwargs)
            except ToolUnavailable as exc:
                return degraded(f"{reason_prefix}: {exc.reason}")
            except Exception as exc:  # noqa: BLE001 — deliberate catch-all
                return degraded(f"{reason_prefix}: {type(exc).__name__}: {exc}")

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator
