# Tool: `transcript`

The most recent meeting transcript for the account, reduced to the lines that
carry buying signal. **Enrichment, not a dependency** (D4).

| | |
|---|---|
| Transport | Google Drive API (Docs exported as text) |
| Consumed by | node `fetch_transcript` (parallel branch 3) |
| Degrades? | **Yes.** Never raises — returns `{found: false, reason}` |
| Live phase | 2.3 |
| Mode env | `TRANSCRIPT_MODE` (falls back to `TOOL_MODE`) |

## Contract

```python
from deal_rescue.tools.transcript import get_tool
tool = get_tool()

tool.fetch_latest("Meridian Fabrication", deal_id="006MER0000000001") -> {
  "found": True,
  "doc_id": "1MeridianDemoTranscriptDocId",
  "doc_title": "... 2026-07-14 — Transcript",
  "meeting_date": "2026-07-14",
  "excerpts": [{"speaker": "Dana Kowalski", "text": "..."}],
  "reason": None,
}
```

`meeting_date` is load-bearing: synthesis cites the transcript as
`"transcript:<meeting_date>"`, and the gate rejects a `meeting`-type milestone
whose date matches neither this date nor a logged activity.

## Modes

**fake** — `fixtures/transcript_cache/<account-slug>.json` if present, else the
curated `fixtures/meridian/transcript.json`, else degraded.

**live** (Phase 2.3) — Drive-only lookup:

1. `files.list` — `q="'<GOOGLE_DRIVE_FOLDER_ID>' in parents and name contains
   '<account>'"`, `orderBy=modifiedTime desc`, `pageSize=1`.
2. `files.export(mimeType="text/plain")`.
3. `parse_transcript_text()` → `[{speaker, text}]` (implemented, unit-tested).
4. `select_excerpts()` keeps lines containing intent vocabulary — budget,
   timeline, signoff, turnaround, next step … (`INTENT_KEYWORDS` in `contract.py`).

Enable with `TRANSCRIPT_MODE=live`, `GOOGLE_CREDENTIALS_PATH`,
`GOOGLE_DRIVE_FOLDER_ID`. A service account with `drive.readonly` on that one
folder is enough — do not grant domain-wide scopes for the demo.

`VERIFY` (spec §4.2 N5): Meet REST API vs Drive-only. Drive-only is chosen here
because it needs no Meet admin scope; revisit only if transcript naming turns out
to be unreliable.

## Tests

`tests/tools/test_transcript.py`

- Meridian fixture returns four excerpts and meeting_date `2026-07-14`
- unknown account degrades instead of raising
- `parse_transcript_text()` attributes speakers and folds continuation lines
- `select_excerpts()` keeps only intent-bearing lines, in document order
- `meeting_date_from_title()` pulls the ISO date out of a Doc title

## Demo data

A fabricated Meridian transcript dated 2026-07-14 lives as a real Google Doc in
the demo Workspace so the live pipe has something to find (spec §9). The fixture
in this repo mirrors it — keep them in sync when the Doc changes.
