# Configuration

`src/deal_rescue/settings.py` is the only module that reads the environment.
Copy `.env.example` to `.env` and edit.

## Global

| Variable | Default | Meaning |
|---|---|---|
| `TOOL_MODE` | `fake` | Default mode for every tool: `fake` \| `live` |
| `AS_OF` | unset | Deterministic "today". Unset = real date. The demo pins `2026-09-20` |
| `STALL_DAYS` | `14` | A deal is stalled after this many days of silence |
| `SHORTLIST_N` | `5` | How many deals the daily shortlist keeps |
| `MAX_SYNTH_RETRIES` | `2` | Synthesis retries after a validation rejection |

`AS_OF` matters more than it looks: the rubric, the shortlist and the golden
record all key off it. Leave it pinned for demos, unset it in production.

## Score weights (spec §7)

| Variable | Default | Deduction |
|---|---|---|
| `SCORE_DAYS_SILENT_CAP` | `45` | Cap on days-silent before weighting |
| `SCORE_DAYS_SILENT_WEIGHT` | `1.0` | × capped days silent |
| `SCORE_CLOSE_DATE_PUSH_WEIGHT` | `8.0` | × close-date pushes |
| `SCORE_STAGE_REGRESSION_WEIGHT` | `15.0` | × stage regressions |
| `SCORE_ACTIVITY_SLOPE_WEIGHT` | `10.0` | if activity is declining |
| `SCORE_ACTIVITY_SLOPE_WINDOW_DAYS` | `30` | Half-window; slope compares last 30d vs prior 30d |
| `SCORE_LLM_ADJUSTMENT_BOUND` | `15` | Max ± the agent may move the score |

D12: configurable by design, no UI. Changing a weight changes the golden record —
update `fixtures/meridian/synthesis_golden.json` in the same commit.

## Per-tool

| Tool | Mode var | Credentials |
|---|---|---|
| `salesforce_reads` | `SF_MODE` | `SF_MCP_URL`, `SF_INSTANCE_URL`, `SF_CLIENT_ID`, `SF_USERNAME`, `SF_PRIVATE_KEY_PATH` |
| `salesforce_writeback` | `SF_WRITEBACK_MODE` | same connection |
| `web_research` | `WEB_MODE` | `SEARCH_PROVIDER` (`tavily`), `SEARCH_API_KEY` |
| `transcript` | `TRANSCRIPT_MODE` | `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_DRIVE_FOLDER_ID` |
| `agentforce` | `AGENTFORCE_MODE` | `AGENTFORCE_MCP_URL`, `AGENTFORCE_AGENT_ID`, `AGENTFORCE_API_URL` |
| `storymydata` | `STORYMYDATA_MODE` | `STORYMYDATA_BASE_URL`, `STORYMYDATA_API_KEY` (optional) |

An unset per-tool mode inherits `TOOL_MODE`.

## Demo-only

| Variable | Values | Effect |
|---|---|---|
| `AGENTFORCE_FAKE_FAULT` | `invented_date` \| `invented_source` \| `permanent` | Makes the fake agent emit ungrounded output so the gate and retry loop can be shown live |

Fake-mode only — ignored when `AGENTFORCE_MODE=live`.

## Tracing

| Variable | Notes |
|---|---|
| `LANGSMITH_TRACING` | `true` to trace |
| `LANGSMITH_API_KEY` | required when tracing |
| `LANGSMITH_PROJECT` | `deal-rescue-agent` |

LangSmith is read by the SDK straight from the environment — no code owns it.
Every rescue run should produce a full trace; Phase 3 pulls the cost numbers for
the demo's cost table out of those traces.

## Paths

| Variable | Default | Notes |
|---|---|---|
| `FIXTURES_DIR` | `<repo>/fixtures` | Fake-mode data |
| `STATE_DIR` | `<repo>/.runs` | Shortlist cache, story payloads, write-back payloads. Gitignored |
