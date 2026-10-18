# Tool: `storymydata`

Turns the synthesized timeline into an enriched Deal Replay on the StoryMyData
web platform. The **in-org** Deal Replay package stays native-data-only — the
enriched replay (external milestones) goes through the platform by design, not
by limitation (spec §0.2).

| | |
|---|---|
| Transport | Plain HTTPS — `POST /api/story` |
| Consumed by | node `publish` |
| Degrades? | **No.** A failed publish fails the run |
| Live phase | 2.5 |
| Mode env | `STORYMYDATA_MODE` (falls back to `TOOL_MODE`) |

## Contract

```python
from deal_rescue.tools.storymydata import get_tool, synthesis_to_story_request
tool = get_tool()

request = synthesis_to_story_request(synthesis, org_data)  # SynthesisOutput -> engine shape
tool.create_story(request)  # -> StoryResult(ok, url, shape, template, issues)
```

`synthesis_to_story_request()` is the adapter — see *Mapping decisions* below for
what it does to the timeline and why.

### The endpoint already exists — verified, not assumed

Read from `Story-engine/app/functions/api/story.js`:

```
POST /api/story
body: {table, description?, milestones?, shape?, template?, adjustments?, target?}
200 : {ok, url, shape, template, periods, rows|players, issues, chars}
4xx : {ok: false, error}
```

- **No auth.** CORS `*`, per-IP daily cap (`API_DAILY_LIMIT`, default 300/day),
  enforced through the `USAGE` KV binding.
- **Nothing is stored** — the whole story travels inside the returned `#s=…` URL.
- `table` is *text* (TSV/CSV/pipe/markdown) and the engine re-parses it with its
  own deterministic numeric parser. That is a feature: D6 survives the boundary
  because no LLM-written number is trusted on either side.
- `milestones` accepts a string (`period | title | desc` lines) or an array of
  `{period, title, desc}`.

`STORYMYDATA_API_KEY` is optional here — if set, it goes out as a bearer token.
Leave it unset against the current public endpoint.

## Mapping decisions (`mapping.py`)

**Stage progress is the driving metric, not amount.** A stalled deal's amount is
flat across its whole history and would render as a straight line. The stage
ordinal moves — and moves *backwards* on a regression — so the animation shows
the real story. Amount rides along as the second column.

```
Period      Stage progress  Amount
2026-03-04  2               $240,000
2026-03-28  3               $240,000
...
2026-08-22  4               $240,000     <- regression: 5 -> 4
```

**Milestones carry `rowIndex`.** Every stage change in one deal shares a year, so
the engine's year-based anchoring would spread them evenly across the run instead
of landing them where they happened. `anchorLong()` in `Story-engine/app/js/milestones.js`
already supports exact `rowIndex` placement — added, per its own comment, for
Salesforce stage history. External and meeting milestones get a *fractional*
index interpolated between the stage rows that surround them in time, so
"champion departed 8/20" lands between the 6/10 and 8/22 rows.

### ⚠ One upstream change needed in Story-engine

`normalizeMilestones()` in `app/functions/api/story.js` maps the array branch to
`{periodRaw, title, desc, anchorYear}` — it **drops `rowIndex`**. Until that is
passed through, milestones posted via the API fall back to year-based anchoring
and every deal milestone piles into the same year group.

Fix is ~2 lines in that function (carry `rowIndex` through when finite); then
`VERIFY` that `share.js` encodes it into the `#s=` payload and `anchorLong()`
receives it on the replay side. Track this as Phase 2.5's first task — the
adapter here already emits it, so nothing changes on this side.

## Modes

**fake** — no network. Writes the exact request body it would have posted to
`.runs/stories/<hash>.json` (diff-friendly) and returns a deterministic
`#s=fake-<hash>` URL. Use it to review mapping changes without spending quota.

**live** — fully wired; set `STORYMYDATA_MODE=live` and `STORYMYDATA_BASE_URL`
(e.g. `https://storymydata.com`). Raises `ToolError` on 429 or `{ok: false}`
rather than publishing a silently wrong story.

## Tests

`tests/tools/test_storymydata.py`

- `build_table()` emits the header + one row per stage change with `$` amounts
- `stage_ordinal()` maps the pipeline and falls back to 1 for unknown stages
- `row_index_for()` — exact match, interpolation, before-first, after-last
- Meridian golden synthesis maps to 5 table rows and 6 milestones, every
  milestone with a `rowIndex` inside `[0, 4]`
- fake writes the request body and returns a stable URL for identical input
