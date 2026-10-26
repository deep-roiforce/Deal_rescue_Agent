# Architecture

Source of truth for *what* this builds: `deal-rescue-agent-spec.md` (the build
spec). This file is the source of truth for *where it lives in code*.

## One paragraph

A daily job ranks stalled opportunities. A human picks one ("run Meridian").
Three fetchers run in parallel — Salesforce (always), web research (maybe),
meeting transcript (maybe). A deterministic rubric scores the deal. An
Agentforce agent synthesizes one JSON: milestones, table data, an email draft, a
score adjustment with signals, and a source list. A schema-and-grounding gate
accepts or rejects it, with up to two retries carrying the rejection reasons
back. On acceptance the orchestrator creates an enriched Deal Replay on
StoryMyData and writes score, signals, replay URL, draft and audit records back
to Salesforce. The rep approves in Salesforce and **Salesforce sends the email**.

## Component map

```
[Salesforce org] ── MCP reads ──▶ [Orchestrator: LangGraph + FastAPI]
      ▲                                │
      │  write-back via MCP:           ├─▶ fetch_org        (salesforce_reads)  ┐
      │  score, signals, draft,        ├─▶ fetch_web        (web_research)      ├ parallel
      │  replay URL, audit tasks       ├─▶ fetch_transcript (transcript)        ┘
      │                                ▼
      │                          assemble  — deterministic score (scoring.py)
      │                                ▼
      │                          synthesize (agentforce via MCP)
      │                                ▼
      │                          validate   — schema + grounding gate, retry ≤2
      │                                ▼
      └────────────────────────── publish ─▶ StoryMyData  (storymydata)
[Rep approves in Salesforce] ─▶ [Salesforce sends natively]  — orchestrator not involved
```

## Where everything is

| Concern | Module |
|---|---|
| Graph wiring | `src/deal_rescue/graph.py` |
| Graph state | `src/deal_rescue/state.py` |
| Nodes (one file each) | `src/deal_rescue/nodes/` |
| Tools (one package each) | `src/deal_rescue/tools/<tool>/` |
| Output contract | `src/deal_rescue/schemas.py` |
| Validation gate | `src/deal_rescue/validation.py` |
| Score rubric | `src/deal_rescue/scoring.py` |
| Shortlist + deal resolution | `src/deal_rescue/shortlist.py` |
| HTTP surface | `src/deal_rescue/api.py` |
| CLI | `src/deal_rescue/cli.py` |
| Settings (the only reader of env) | `src/deal_rescue/settings.py` |

## Nodes

Every node is a plain `(state, settings) -> partial state` function, unit-testable
without building the graph.

| Node | File | Contract |
|---|---|---|
| `fetch_org` | `nodes/fetch_org.py` | The floor. On failure sets `status="failed_fetch_org"` and the run ends. |
| `fetch_web` | `nodes/fetch_web.py` | Never raises. Degrades to `{found: false, reason}`. |
| `fetch_transcript` | `nodes/fetch_transcript.py` | Never raises. Degrades to `{found: false, reason}`. |
| `assemble` | `nodes/assemble.py` | Fan-in. Computes `score_base` from the rubric, or ends the run. |
| `synthesize` | `nodes/synthesize.py` | Calls Agentforce with `prior_errors`. Bumps `retries`. |
| `validate` | `nodes/validate.py` | The gate. Routes to publish / synthesize / END. |
| `publish` | `nodes/publish.py` | StoryMyData create_story, then Salesforce write-back. |

## Tools

Six integrations, one package each, all with the same five-file layout. See
[tools.md](tools.md) and each tool's own README.

| Tool | Node | Degrades? |
|---|---|---|
| `salesforce_reads` | `fetch_org`, shortlist | no — fatal |
| `web_research` | `fetch_web` | yes |
| `transcript` | `fetch_transcript` | yes |
| `agentforce` | `synthesize` | no — but bad output is a validation failure |
| `storymydata` | `publish` | no |
| `salesforce_writeback` | `publish` | no |

## Terminal states

| `status` | Meaning |
|---|---|
| `published` | Replay created, records written. The rep can approve. |
| `failed_fetch_org` | No CRM data. Nothing to synthesize. |
| `failed_synthesize` | Agentforce transport failure. |
| `failed_validation` | Output could not be grounded in 3 attempts. **This is a success of the design, not a bug.** |
| `failed_publish_story` / `failed_publish_writeback` | Downstream write failed after a valid synthesis. |

## What is deliberately *not* here

No email send path. No Platform Events. No ReAct agent. No Postgres
checkpointing. No ranking-weights UI. See §12 of the spec.
