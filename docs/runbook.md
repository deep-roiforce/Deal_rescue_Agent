# Runbook

## Install

Requires Python 3.11+ (nothing runs without it — it is not currently installed on
the build machine).

```bash
python -m venv .venv
```

```bash
.venv/Scripts/activate
```

```bash
pip install -e ".[graph,api,dev]"
```

```bash
cp .env.example .env
```

## Run the tests

```bash
pytest
```

`tests/test_graph.py` skips itself if the `graph` extra is missing; everything
else runs on fixtures alone.

## Drive it from the CLI

```bash
python -m deal_rescue.cli shortlist
```

```bash
python -m deal_rescue.cli rescue meridian
```

Expected: `status published`, score `34` (base `40`, adj `-6`), a replay URL, and
the deterministic signals listed above the LLM's.

## Drive it from the API

```bash
uvicorn deal_rescue.api:app --reload
```

```bash
curl -s localhost:8000/healthz
```

```bash
curl -s -X POST localhost:8000/rescue -H "Content-Type: application/json" -d "{\"query\":\"meridian\"}"
```

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Which mode each tool is in |
| `GET /shortlist` | Current ranked shortlist |
| `POST /shortlist/refresh` | Rebuild it now (N1) |
| `POST /rescue {query}` | Resolve a deal and run the graph; 400 with candidates if ambiguous |

## Show the validation gate live

```bash
AGENTFORCE_FAKE_FAULT=invented_date python -m deal_rescue.cli rescue meridian --json
```

The agent invents an 2026-08-05 "budget approved" milestone with nothing behind
it. The gate rejects it, hands the reason back, and attempt 2 publishes —
`retries: 2`, `status: published`.

```bash
AGENTFORCE_FAKE_FAULT=permanent python -m deal_rescue.cli rescue meridian
```

Three attempts, then `status: failed_validation` and nothing published. **This is
the design working**, and it is the slide that separates this from piping an LLM
into an API.

## Inspect what a run produced

```bash
ls .runs/stories .runs/writebacks
```

`.runs/stories/<hash>.json` is the exact body that would go to
`POST /api/story`; `.runs/writebacks/<deal_id>.json` is exactly what would land
in the org.

## Go live, one pipe at a time

Phase 2 order (spec §10) — flip one variable, re-run `pytest`, keep going:

1. `SF_MODE=live` — org reads + shortlist
2. `WEB_MODE=live` — search with cache write-through
3. `TRANSCRIPT_MODE=live` — Google Doc lookup
4. `AGENTFORCE_MODE=live` — synthesis via MCP
5. `STORYMYDATA_MODE=live` — real replay URLs
6. `SF_WRITEBACK_MODE=live` — records in the org

Definition of done per pipe: the node works against the real service **and**
still degrades gracefully when it is down — except `fetch_org`, which fails the
run by design.

## Demo day checklist

- [ ] `AS_OF=2026-09-20` pinned so the numbers match the script
- [ ] `LANGSMITH_TRACING=true` and a trace open in a tab
- [ ] `pytest` green — the golden record is the claim
- [ ] Deal Replay package rebuilt fresh (never a stale Desktop zip)
- [ ] Enriched replay recorded from the StoryMyData **web** platform
