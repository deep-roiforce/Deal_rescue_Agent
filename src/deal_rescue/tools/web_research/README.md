# Tool: `web_research`

Outside-world signals about the account: expansion news, people changes, job
postings. **Enrichment, not a dependency** — if it returns nothing, the run
continues and the email gets thinner (D4, D11).

| | |
|---|---|
| Transport | HTTPS, one provider (Tavily by default) |
| Consumed by | node `fetch_web` (parallel branch 2) |
| Degrades? | **Yes.** Never raises — returns `{found: false, reason}` |
| Live phase | 2.2 |
| Mode env | `WEB_MODE` (falls back to `TOOL_MODE`) |

## Contract

```python
from deal_rescue.tools.web_research import get_tool
tool = get_tool()

tool.search("Meridian Fabrication") -> {
  "found": True,
  "items": [{"id": "expansion_pr_2026-09-02", "title": ..., "url": ...,
             "snippet": ..., "signal_type": "expansion",
             "date": "2026-09-02", "source_name": ...}],
  "reason": None,
}
```

`item.id` matters: synthesis cites evidence as `"web:<id>"` in `sources`, and the
validation gate rejects any source id that was not in this payload. Ids must be
stable for the same result across runs, which is why `make_id()` is
title-slug + date rather than a hash of the whole row.

`signal_type` is one of `expansion | people_change | news | jobs`.

## Modes

**fake** — reads `fixtures/web_cache/<account-slug>.json` if present, else the
curated `fixtures/meridian/web_findings.json` for Meridian, else returns a
degraded payload. The filler shortlist deals deliberately have no cache entry, so
running one of them exercises the thin-evidence path end to end.

**live** (Phase 2.2) — `default_queries()` builds the three queries from spec
§4.2 N4; `normalize()` maps provider rows onto the contract and is pure/unit-tested;
successful searches write through to the same cache the fake reads. To enable:
`WEB_MODE=live`, `SEARCH_PROVIDER=tavily`, `SEARCH_API_KEY=...`.

The `@never_raise("web search failed")` decorator on `LiveWebResearch.search` is
what makes D4 true in code — a provider outage becomes `found: false`, not a
failed run. Keep it if you swap providers.

## Tests

`tests/tools/test_web_research.py`

- Meridian cache/fixture returns three classified items with stable ids
- unknown account degrades instead of raising
- `normalize()` drops rows without title/url and de-duplicates by url
- `classify()` maps expansion / people-change / jobs wording correctly
- a provider that throws still yields `{found: false}` (D4)

## Demo note

The people-change signal is attributed to a "people-data provider", not scraped
from LinkedIn. Keep that attribution in any live provider you add.
