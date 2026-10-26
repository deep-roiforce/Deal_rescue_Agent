"""Typed contract for meeting-transcript enrichment."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class Excerpt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    speaker: str | None = None


class TranscriptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    found: bool
    doc_id: str | None = None
    doc_title: str | None = None
    meeting_date: date | None = None
    excerpts: list[Excerpt] = Field(default_factory=list)
    reason: str | None = None

    def as_state(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class TranscriptTool(Protocol):
    def fetch_latest(self, account_name: str, *, deal_id: str | None = None) -> dict[str, Any]:
        """Always returns a JSON-safe dict. Never raises (D4)."""
        ...


# Keyword windowing for excerpt extraction (spec 4.2 N5: "simple keyword
# windowing is fine for demo").
INTENT_KEYWORDS = (
    "budget",
    "timeline",
    "internally",
    "socialize",
    "signoff",
    "sign-off",
    "approval",
    "turnaround",
    "pain",
    "priority",
    "next step",
    "procurement",
    "pilot",
)


def select_excerpts(
    lines: list[dict[str, Any]], keywords: tuple[str, ...] = INTENT_KEYWORDS, limit: int = 8
) -> list[Excerpt]:
    """Keep lines that carry buying-signal vocabulary, in document order."""
    picked: list[Excerpt] = []
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        if any(word in text.lower() for word in keywords):
            picked.append(Excerpt(text=text, speaker=line.get("speaker")))
        if len(picked) >= limit:
            break
    return picked
