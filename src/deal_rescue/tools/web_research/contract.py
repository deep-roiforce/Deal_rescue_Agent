"""Typed contract for outside-world signals about the account."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

SignalType = Literal["expansion", "people_change", "news", "jobs"]


class WebItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str  # stable slug -- `sources` entries reference it as "web:<id>"
    title: str
    url: str
    snippet: str = ""
    signal_type: SignalType = "news"
    date: dt.date | None = None
    source_name: str | None = None


class WebFindings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    found: bool
    items: list[WebItem] = Field(default_factory=list)
    reason: str | None = None

    def as_state(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class WebResearchTool(Protocol):
    def search(self, account_name: str, *, queries: list[str] | None = None) -> dict[str, Any]:
        """Always returns a JSON-safe dict. Never raises (D4)."""
        ...


def default_query_plan(account_name: str) -> list[tuple[str, str]]:
    """Spec 4.2 N4, as (query, topic) pairs.

    The topic is load-bearing, not a detail. Tavily only returns
    `published_date` on its news topic; on the general topic every result comes
    back dateless. An undated web item cannot ground an `external` milestone --
    the gate checks the milestone's date against the dates we actually fetched
    -- so a general-topic search silently costs us every outside-world
    milestone in the replay.

    Job postings are not news and genuinely have no publication date, so that
    query stays general and its findings are cited without a date.
    """
    quoted = f'"{account_name}"'
    return [
        (f"{quoted} news", "news"),
        (f"{quoted} expansion OR announcement OR investment", "news"),
        (f"{quoted} careers OR hiring", "general"),
    ]


def default_queries(account_name: str) -> list[str]:
    """Queries only, without topics."""
    return [query for query, _topic in default_query_plan(account_name)]


def slugify(account_name: str) -> str:
    cleaned = account_name.lower().replace("&", "and")
    return "-".join(part for part in cleaned.split() if part)
