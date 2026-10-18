"""Live web research (Phase 2.2).

One live provider plus a pre-seeded cache, per spec 12 ("no additional web
sources beyond one live + cache"). The normalization half is fully implemented
and unit-tested; only the HTTP call needs credentials.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import httpx

from deal_rescue.settings import HTTP_TIMEOUT, Settings
from deal_rescue.tools.base import ToolNotImplemented, ToolUnavailable, never_raise
from deal_rescue.tools.web_research.curated import curated_findings
from deal_rescue.tools.web_research.contract import (
    WebFindings,
    WebItem,
    default_query_plan,
    slugify,
)

TAVILY_URL = "https://api.tavily.com/search"
NEWS_WINDOW_DAYS = 365

# Order matters: the first match wins, so the most specific signals come first.
# Keywords earn their place by surviving real results -- "investment" was here
# and tagged every stock-tip article as an expansion, so it is gone.
_SIGNAL_KEYWORDS = {
    "people_change": (
        "appointed", "named ceo", "to become", "succeeds", "steps down",
        "departs", "resigns", "retires", "joins", "promoted", "new chief",
    ),
    "expansion": (
        "expansion", "expands", "new plant", "new facility", "groundbreaking",
        "opens plant", "capacity",
    ),
    "jobs": ("hiring", "job posting", "careers", "now hiring", "open role", "apply now"),
}


def classify(title: str, snippet: str) -> str:
    haystack = f"{title} {snippet}".lower()
    for signal, words in _SIGNAL_KEYWORDS.items():
        if any(word in haystack for word in words):
            return signal
    return "news"


def parse_date(value: Any) -> date | None:
    """Provider date -> date, or None.

    Tavily returns RFC 2822 on its news topic ("Wed, 15 Jul 2026 00:00:00 GMT")
    and nothing at all on the general topic. Other providers use ISO. Both are
    handled here rather than assumed, because an unparsed date silently costs
    the run every external milestone: the gate checks a milestone's date
    against the dates we actually fetched.
    """
    if not value:
        return None
    text = str(value).strip()

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        pass

    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        return None


def source_of(url: str) -> str | None:
    """Publisher host, for the audit trail. "clarionledger.com" tells a rep
    more about a claim than a bare URL does."""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else (host or None)


def make_id(title: str, published: date | None) -> str:
    stem = "-".join(title.lower().split()[:4])
    stem = "".join(ch for ch in stem if ch.isalnum() or ch == "-")
    return f"{stem}_{published.isoformat()}" if published else stem


def normalize(raw_results: list[dict[str, Any]]) -> list[WebItem]:
    """Provider payload -> contract items. Pure function; unit-tested."""
    items: list[WebItem] = []
    seen: set[str] = set()
    for row in raw_results:
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url or url in seen:
            continue
        seen.add(url)
        snippet = (row.get("content") or row.get("snippet") or "").strip()
        published = parse_date(row.get("published_date") or row.get("date"))
        items.append(
            WebItem(
                id=make_id(title, published),
                title=title,
                url=url,
                snippet=snippet[:400],
                signal_type=classify(title, snippet),
                date=published,
                source_name=row.get("source") or source_of(url),
            )
        )
    return items


class LiveWebResearch:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Fetched results are working state, not fixtures.
        self.cache_dir = settings.state_dir / "web_cache"

    def _fetch(self, query: str, topic: str = "news") -> list[dict[str, Any]]:
        if self.settings.search_provider != "tavily":
            raise ToolNotImplemented(
                f"search provider '{self.settings.search_provider}' not implemented; use tavily"
            )
        if not self.settings.search_api_key:
            raise ToolUnavailable("SEARCH_API_KEY is not set")

        payload: dict[str, Any] = {
            "api_key": self.settings.search_api_key,
            "query": query,
            "max_results": 5,
            "search_depth": "basic",
            "topic": topic,
        }
        if topic == "news":
            # Only the news topic carries published_date, and only within a
            # window. A year covers the signals a stalled deal cares about.
            payload["days"] = NEWS_WINDOW_DAYS

        response = httpx.post(TAVILY_URL, json=payload, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json().get("results", [])

    @never_raise("web search failed")
    def search(self, account_name: str, *, queries: list[str] | None = None) -> dict[str, Any]:
        # Fictional demo accounts must never be grounded on real articles about
        # the wrong company -- live search for "Meridian Fabrication" returned a
        # footwear brand and a kiosk vendor. Curated findings win; the live pipe
        # covers every real account.
        curated = curated_findings(self.settings.fixtures_dir, account_name)
        if curated is not None:
            return curated

        plan = (
            [(query, "news") for query in queries]
            if queries
            else default_query_plan(account_name)
        )

        raw: list[dict[str, Any]] = []
        for query, topic in plan:
            raw.extend(self._fetch(query, topic))

        items = normalize(raw)
        findings = WebFindings(
            found=bool(items),
            items=items,
            reason=None if items else "no results from provider",
        )
        self._write_cache(account_name, findings)
        return findings.as_state()

    def _write_cache(self, account_name: str, findings: WebFindings) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path: Path = self.cache_dir / f"{slugify(account_name)}.json"
        path.write_text(json.dumps(findings.as_state(), indent=2), encoding="utf-8")
