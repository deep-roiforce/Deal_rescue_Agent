# Deal Rescue Agent — Build Specification

**Audience:** Claude Code (implementation agent). This document is the source of truth for architecture and contracts. Where it says `VERIFY-IN-REPO`, the local repositories override this document — read them first, do not trust this spec's assumptions there.

**Owner:** Deep — Salesforce Architect (Agentforce, Data Cloud, multi-LLM). This is the flagship demo for job-search positioning and ROI-Force (consulting for industrial/manufacturing Salesforce clients).

**Status:** Architecture LOCKED (2026-09-20). Do not redesign. Implement as specified; raise blockers, don't invent alternatives.

---

## 0. Context for Claude Code — read this first

1. **Catch up on StoryMyData before writing any StoryMyData integration code.** This spec's author has incomplete knowledge of recent StoryMyData progress. Local repos to read:
   - `Story-engine` — web app + animation engine (public product: StoryMyData, storymydata.com). Has table mode, document/RAG mode, web-search mode, and templates (Horse Rider, Cloud Hop, a comparison template). `VERIFY-IN-REPO`: current API surface, auth, milestone/table input format, whether a public API endpoint exists or must be added.
   - `storymydata-salesforce` — SFDX package ("Deal Replay") that plays animations inside a Salesforce org from a static resource. Core invariant: **no callouts from the org, native org data only**. Branch `master`, no remote, local machine only.
   - `Story-slack-bot` — sibling repo, not in scope for this build.
2. **The enriched replay (external milestones: web events, transcript moments) goes through the StoryMyData web platform/API — never through the in-org package.** The in-org package stays native-data-only. This is a deliberate product-tier decision, not a limitation to fix.
3. Existing assets to reuse, not rebuild:
   - An external orchestrator/API that calls LLMs directly (the "~50x cheaper than Agentforce" prompt-template system). `VERIFY-IN-REPO` for its current shape; this build wraps/extends it, structured as LangGraph.
   - A Salesforce + AWS Bedrock email-processing pipeline (separate project; pattern reference only).
4. **Demo-first scoping.** This is a 2–3 week demo build (fictional customer "Meridian Fabrication"), not production SaaS. Prefer the simplest implementation that makes the real pipes work. Semi-scripted/curated data is acceptable where marked, as long as the architecture pipes are real.

---

## 1. What this system does (one paragraph)

A daily job produces a shortlist of stalled Salesforce opportunities ranked by a deterministic criticality score. A user picks one ("run Meridian"). The orchestrator fires three fetchers **in parallel**: Salesforce MCP (opportunity history, contacts, activities — always available, the reliability floor), web research (news/job postings — may be empty), and a Google Meet/Gemini transcript from Google Cloud (may be null). An **Agentforce agent synthesizes** everything into one schema-validated JSON: milestones + table data (for StoryMyData), an email draft, a deal score with visible signals, and a sources list. The orchestrator calls the StoryMyData API to create an enriched Deal Replay and writes everything back to Salesforce (draft, score, replay link, audit records). The rep approves in Salesforce; **Salesforce sends the email natively** (no Gmail, no external send). The replay shows the deal's story including external-world milestone markers.

---

## 2. Locked architecture decisions (do not reopen)

| # | Decision | Rationale (for docs/demo narration) |
|---|---|---|
| D1 | **Pull-based daily shortlist**, not Platform Events / real-time | Stalls aren't minute-urgent; batch matches sales rhythm; simpler. Write-up notes the same pipeline can run event-driven for urgent triggers (mention only, don't build). |
| D2 | **Human picks the deal from the shortlist** (conversational: "run Meridian") | Human stays in the selection seat; research cost only on demand. |
| D3 | Three fetchers run **in parallel** (LangGraph fan-out), never sequentially | Latency; null-handling already covers stragglers. |
| D4 | **Graceful degradation**: transcript/web may return null; Salesforce MCP data is the floor. Nulls flow through state; nodes never raise for missing external data | "External sources are enrichment, not dependencies." |
| D5 | **Agentforce is the synthesis step** (merge + judgment), exposed to the orchestrator via MCP. Reads are NOT done through Agentforce | Governed judgment where the client already pays for governance; deterministic reads stay cheap via API/MCP. |
| D6 | **LLM never touches numbers.** Dates, amounts, stage names pass through deterministically from org data. LLM selects, labels, annotates | Prevents hallucinated milestones; prompt-template merge fields ground this. |
| D7 | **Schema validation gate** on Agentforce output, reject-and-retry (max 2), then error state | The slide that separates this from "piped ChatGPT into an API". |
| D8 | **No Gmail MCP. Email draft, approval, and send are all native Salesforce** | Native activity logging, sharing rules, sender identity. Zero external send surface. |
| D9 | Deal score = **deterministic rubric core** (days silent, close-date pushes, stage regression, activity slope) + LLM adjustment within bounds, with stated signals | A score with visible reasons; never a bare LLM number. |
| D10 | Orchestrator = **own service structured as LangGraph**, traced with **LangSmith**. Deterministic graph (fixed nodes/edges); LLM judgment confined to triage tie-breaks and synthesis. No free-roaming ReAct agents | Reliable demos; iterative tool-adding via new nodes. |
| D11 | Thin-evidence rule: if web AND transcript are empty, the email draft is shorter, org-grounded only, and the response flags "low context — consider a call" | No confident filler slop. |
| D12 | Shortlist ranking v1 = `amount × stall_days` (configurable by design; **no config UI in demo**) | Configurability is mentioned, not built. |

---

## 3. Component map

```
[Salesforce org] ── daily scheduled export / MCP query ──▶ [Orchestrator (LangGraph, FastAPI)]
      ▲                                                        │
      │  write-back via Salesforce MCP:                        ├─▶ fetch_org (Salesforce MCP)      ┐
      │  score, email draft, replay URL,                       ├─▶ fetch_web (search API)          ├─ parallel
      │  audit/activity records                                ├─▶ fetch_transcript (Google APIs)  ┘
      │                                                        ▼
      │                                              synthesize (Agentforce via MCP)
      │                                                        ▼
      │                                              validate_json (schema gate, retry ≤2)
      │                                                        ▼
      └──────────────────────────────────────────────  publish ─▶ StoryMyData API (enriched replay)
[Rep approves in Salesforce] ─▶ [Salesforce sends email natively] (orchestrator not involved)
[StoryMyData web platform] renders enriched replay; in-org Deal Replay package stays native-only
```

---

## 4. Orchestrator implementation (LangGraph)

**Stack:** Python 3.11+, `langgraph`, `langchain-mcp-adapters`, `langsmith` (env-var tracing), FastAPI, `pydantic` for schemas, `httpx`. Host: local/Lambda-ready. `VERIFY-IN-REPO`: current LangGraph API details; this spec gives shape, repo/docs give syntax.

### 4.1 State

```python
class RescueState(TypedDict):
    deal_id: str
    account_name: str
    org_data: Optional[dict]          # from fetch_org; never None after fetch (it's the floor)
    web_findings: Optional[dict]      # {found: bool, items: [...], reason?: str}
    transcript: Optional[dict]        # {found: bool, doc_id?, excerpts?: [...], meeting_date?, reason?: str}
    synthesis: Optional[dict]         # SynthesisOutput (see §6)
    validation_errors: list[str]
    retries: int                      # synthesis retry counter
    replay_url: Optional[str]
    writeback: Optional[dict]         # ids of created SF records
    status: str                       # "running" | "published" | "failed_validation" | "failed_<node>"
```

### 4.2 Nodes (each is a separately implementable function)

Implement each node as its own module with its own tests. Contracts:

**N1. `load_shortlist`** *(outside the rescue graph — a separate daily entry point)*
- Query open opportunities via Salesforce MCP: stage not Closed, last activity > `STALL_DAYS` (default 14) ago.
- Compute `stall_score` per deal — see §7 rubric (deterministic part only).
- Rank by `amount * stall_days` (D12), take top `SHORTLIST_N` (default 5).
- Output: shortlist JSON persisted (SQLite or flat file is fine for demo) + human-readable summary ("5 deals need review: …").
- Trigger: cron/scheduled call to `GET /shortlist/refresh`; also callable on demand.

**N2. `select_deal`** *(API layer, not a graph node)*
- `POST /rescue` with `{query: "meridian"}` → fuzzy-match against shortlist account names → resolve `deal_id`. Ambiguous → 400 with candidates. Then invoke graph.

**N3. `fetch_org`** (graph node, parallel branch 1)
- Via Salesforce MCP tools (see §8): opportunity + OpportunityHistory (stage, amount, close-date changes with dates), contact roles, activity timeline (tasks/emails/events, last 6 months), account fields.
- Returns `{org_data: {...}}`. This node MAY raise on failure — org data is the floor; without it the run is dead. Router sends failures to `END` with `status="failed_fetch_org"`.

**N4. `fetch_web`** (graph node, parallel branch 2)
- One live source for demo: web search API (Tavily or Brave; env-configurable). Queries: `"{account_name}" news`, `"{account_name}" expansion OR announcement`, `"{account_name}" careers OR hiring {relevant title}`.
- Normalize to `{found, items: [{date?, title, url, snippet, signal_type: "expansion"|"people_change"|"news"|"jobs"}]}`.
- Empty/error → `{found: false, reason: "..."}`. **Never raise** (D4).
- Demo note: curated/cached results for Meridian are acceptable; keep the live pipe real (cache layer keyed by account, pre-seeded).

**N5. `fetch_transcript`** (graph node, parallel branch 3)
- Google Meet transcripts land in Drive as Google Docs. Flow: find the Doc for the most recent meeting matching the account (Drive API search by naming convention/folder for demo), export text, extract relevant excerpts (simple keyword windowing is fine for demo — full text also acceptable if short).
- Returns `{found, doc_id, meeting_date, excerpts: [{speaker?, text}]}` or `{found: false, reason}`. **Never raise.**
- Demo data: a fabricated Meridian transcript as a real Doc in a demo Workspace so the pipe is live (§9).
- `VERIFY`: Meet REST API vs. Drive-only lookup — use whichever is simpler with available credentials; Drive-only is fine for demo.

**N6. `synthesize`** (graph node, fan-in target — runs after N3+N4+N5 all complete)
- Calls the **Agentforce agent via MCP** (see §8) with: org_data (verbatim), web_findings, transcript, and `prior_errors: state["validation_errors"]` (empty on first pass; populated on retry so the agent can self-correct).
- The Agentforce side: an agent/prompt template whose merge fields ground all numeric/date/stage values from org_data (D6). Instructions encode D6 (no invented numbers/dates), D11 (thin-evidence behavior), and §6 output schema.
- Returns `{synthesis: <raw JSON>, retries: retries+1}`. Malformed non-JSON → treat as validation failure, not exception.
- `VERIFY-IN-REPO`: whether to invoke Agentforce through the existing orchestrator's Agent API client or a new MCP wrapper — reuse what exists; the demo claim is "Agentforce exposed via MCP", so the MCP wrapper (§8.2) is the deliverable shape.

**N7. `validate_json`** (router / conditional edge)
- Pydantic-validate `state["synthesis"]` against §6 `SynthesisOutput`, PLUS cross-checks:
  - every `milestones[].date` with `type="stage"` exists in `org_data` stage history (exact match);
  - amounts match org_data exactly;
  - `email_draft.to` is a contact present in org_data contact roles;
  - `deal_score.value` within rubric bounds (§7);
  - every item in `sources` corresponds to provided input (no invented sources).
- Pass → `"publish"`. Fail with `retries < 2` → append errors to `validation_errors`, route back to `synthesize`. Fail at limit → `END`, `status="failed_validation"`.

**N8. `publish`** (graph node)
- a) `POST` milestones + table_data to StoryMyData API → `replay_url`. `VERIFY-IN-REPO` (Story-engine): endpoint, auth, exact payload shape — **adapt §6 field names to what the engine actually accepts; the engine's format wins.** If no API endpoint exists yet, adding a minimal authenticated `POST /api/stories` to Story-engine is in scope.
- b) Write back to Salesforce via MCP: deal score + signals (custom fields or a Rescue_Result__c record — simplest viable), the email draft (as a draft EmailMessage or a Task containing the draft + an approval flag field, whichever the org handles cleanest for a native approval→send Flow), replay URL (URL field on Opportunity), and an audit Task per external finding with its source (governance money-shot).
- c) Return `{replay_url, writeback: {...ids}, status: "published"}` → `END`.
- Approval + send after this point are **pure Salesforce** (Flow on the approval flag → native send). Orchestrator's involvement ends here (D8).

### 4.3 Graph wiring

```
START ─▶ fetch_org ──────┐
START ─▶ fetch_web ──────┼─▶ synthesize ─▶ [validate_json router]
START ─▶ fetch_transcript┘        ▲               │ pass → publish → END
                                  └── fail(<2) ───┘ fail(=2) → END(failed_validation)
```
Fan-in is native: `synthesize` has three incoming edges and waits for all. In-memory checkpointer only. No `interrupt()` — approval lives in Salesforce, not the graph (D8, D10).

### 4.4 API surface (FastAPI)

- `GET /shortlist` — current ranked shortlist
- `POST /shortlist/refresh` — run N1 now
- `POST /rescue` `{query}` — resolve deal, run graph, return final state (or job id + `GET /rescue/{id}` if async; sync is fine for demo)
- LangSmith tracing on via env (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`); every rescue run must produce a full trace (demo shows the trace + cost).

---

## 5. Salesforce-side deliverables

- Stall-detection is **computed in the orchestrator** from org data (D1 killed the in-org Flow trigger); Salesforce-side build is only:
  1. Fields: `Rescue_Score__c`, `Rescue_Signals__c` (long text), `Replay_URL__c` on Opportunity (or a `Rescue_Result__c` child object — implementer's choice, keep it simple).
  2. Approval flag field + a record-triggered Flow: on approve → send the drafted email natively, log completion.
  3. Integration user + connected app scoped for the MCP connection (least privilege; read on Opp/Contact/Activity, create on the write-back objects). Document the permission set.
- The **Deal Replay package** (`storymydata-salesforce`) is used as-is for the in-org native replay scene. Known repo caveats the implementer must respect (`VERIFY-IN-REPO`, may be fixed since): stale README/manifest/permission set (covers only M6+M7); rebuild fresh before any demo handover; Workbench-zip path generates its own manifest and is the safe deploy route; do not use any stale zip found on the Desktop.
- Demo-data limitation: OpportunityHistory cannot be inserted/backdated. In-org replay of fictional data will show repeating date labels. **Demo video records enriched replays from the web platform (paste/API mode) with realistic dates**; in-org replay appears only as the "native tier" hook shot.

---

## 6. Synthesis output contract (`SynthesisOutput`)

Field names here are the orchestrator-internal contract; `publish` maps them to StoryMyData's actual API shape (`VERIFY-IN-REPO`, engine wins).

```json
{
  "milestones": [
    {"date": "2026-03-04", "label": "Deal created — $240K quoting system", "type": "stage", "value": 240000},
    {"date": "2026-07-14", "label": "Champion: 'let me socialize this internally'", "type": "meeting"},
    {"date": "2026-08-20", "label": "Champion departed company", "type": "external"},
    {"date": "2026-09-02", "label": "Plant expansion announced", "type": "external"}
  ],
  "table_data": [
    {"date": "2026-03-04", "stage": "Discovery", "amount": 240000},
    {"date": "2026-04-18", "stage": "Proposal", "amount": 240000}
  ],
  "email_draft": {
    "to_contact_id": "003...", "to_name": "…", 
    "subject": "…", "body": "…",
    "grounding_note": "references: expansion PR, 7/14 meeting"
  },
  "deal_score": {
    "value": 34,
    "base_deterministic": 40,
    "llm_adjustment": -6,
    "signals": ["19d silent", "champion departed (web)", "expansion announced (web)", "positive intent in 7/14 transcript"]
  },
  "sources": ["opp_history", "transcript:2026-07-14", "web:expansion_pr_2026-09-02"],
  "evidence_level": "full" 
}
```

Rules enforced by N7: `type ∈ {stage, external, meeting}`; `stage`-type milestones and all `table_data` rows must match org_data exactly (D6); `evidence_level ∈ {full, org_only}` — must be `org_only` when web and transcript both `found:false`, and then `email_draft.body` must be short and org-grounded with a `"low_context_flag": true` field present (D11); `llm_adjustment` bounded to ±15 (§7).

---

## 7. Deal score rubric (deterministic core)

Start at 100, subtract:
- `min(days_silent, 45)` × 1.0
- close-date pushes × 8
- stage regression (any) × 15
- activity slope negative over trailing 60d × 10
Clamp 0–100 → `base_deterministic`. LLM adjustment: ±15 max, must cite a signal for any nonzero adjustment. Final = clamp(base + adjustment, 0, 100). Weights are constants in one config module (D12: configurable by design, no UI).

---

## 8. MCP integrations

### 8.1 Salesforce MCP (org reads + write-backs)
- Prefer **Salesforce's official MCP server** if available to the demo org (`VERIFY`: current availability/auth for the org's edition); else a thin custom MCP server wrapping REST/SOQL with named tools below. Either way, the orchestrator consumes it via `langchain-mcp-adapters`.
- Tools required: `get_opportunity(deal_id)`, `get_opportunity_history(deal_id)`, `get_contact_roles(deal_id)`, `get_activity_timeline(deal_id, months=6)`, `list_stalled_opportunities(stall_days)`, `create_rescue_writeback(payload)` (score/signals/replay_url/draft/audit tasks — may be several tools if cleaner).
- Auth: connected app JWT for the scoped integration user (§5.3). All writes logged as records (auditability is the demo's thesis).

### 8.2 Agentforce via MCP (synthesis)
- Deliverable: a small MCP server exposing one tool, `synthesize_rescue(org_data, web_findings, transcript, prior_errors) -> SynthesisOutput-JSON`, which internally invokes the Agentforce agent (Agent API) whose prompt template implements §6/D6/D11. `VERIFY-IN-REPO`: reuse existing Agent-API client code from the prompt-template project if present.
- Demo narration line this enables (keep in docs): "reads via plain MCP tools, judgment via Agentforce — the runtime is chosen per task; Agentforce where governance earns its cost."

### 8.3 StoryMyData (not MCP — plain HTTPS)
- `create_story(milestones, table_data) -> {replay_url}` against Story-engine. `VERIFY-IN-REPO` everything (§4.2 N8).

---

## 9. Meridian Fabrication — demo dataset (create as fixtures + org data + one Google Doc)

- Account: Meridian Fabrication — $180M metal fabricator, Fort Wayne, IN.
- Opportunity: "Plant 2 Quoting System Replacement", $240K, created 2026-03-04.
- Stage history: Discovery (3/04) → Qualification (3/28) → Proposal (4/18) → Negotiation (6/10). Close date pushed 7/31 → 8/29 → 9/30. Last activity 2026-09-01 (19d silent at demo date 9/20).
- Contacts: VP Ops **Dana Kowalski** (champion — departs in August), Plant Manager **Ray Gutierrez** (becomes new target), CFO **Anne Park**.
- Ghosted email thread: rep follow-ups 8/12, 8/21, 9/01 — no replies (seed as Tasks/EmailMessages).
- Transcript (fabricated, saved as a real Google Doc in demo Workspace, dated 2026-07-14): Dana says the "socialize this internally" line, Ray raises quoting-turnaround pain, budget confirmed for FY27.
- Web findings (curated cache): (a) 2026-08-20 people-change signal — Dana Kowalski now at another company (attribute to "people-data provider", not scraped LinkedIn); (b) 2026-09-02 local business journal: Meridian announces Plant 3 expansion; (c) job posting: "Estimating/Quoting Supervisor".
- Expected outputs (golden fixtures for tests): the §6 example above IS the Meridian golden record — expected milestones, score ≈ 34, email to Ray referencing expansion + 7/14 meeting.
- Plus 4 filler shortlist deals (varying amounts/stall days) so the shortlist scene shows real ranking.

---

## 10. Build phases & definition of done

**Phase 1 — skeleton (no external deps):** graph with all nodes stubbed against Meridian fixtures; validation gate + retry loop working; LangSmith tracing live. DoD: `POST /rescue {"query":"meridian"}` returns published state from fixtures with a full trace.

**Phase 2 — real pipes, one at a time:** (1) Salesforce MCP reads + shortlist, (2) web search live w/ cache, (3) Google Doc transcript fetch, (4) Agentforce synthesis via MCP, (5) StoryMyData create_story, (6) SF write-back + approval Flow. DoD per pipe: node passes with the real service AND still degrades gracefully when the service is down (except fetch_org, which fails the run by design).

**Phase 3 — demo hardening:** golden-record test (Meridian in → expected milestones/score out, numbers byte-exact per D6); cost captured from LangSmith traces for the demo's cost table; fresh rebuild of the Deal Replay package; record enriched replay from web platform.

**Testing philosophy** (mirrors the SF package's ethos): test the honesty rules, not just arithmetic — numbers-pass-through (D6), thin-evidence behavior (D11), validation rejection of an invented date, score bounds, no-invented-sources.

---

## 11. Env/config (single settings module)

`SF_*` (connected app / MCP endpoint), `AGENTFORCE_*` (agent id, MCP endpoint), `SEARCH_API_KEY` + provider, `GOOGLE_*` (service-account or OAuth for Drive), `STORYMYDATA_*` (base URL, key — `VERIFY-IN-REPO`), `LANGSMITH_*`, `STALL_DAYS=14`, `SHORTLIST_N=5`, `MAX_SYNTH_RETRIES=2`, score weights.

## 12. Explicitly out of scope (do not build)

Gmail/any external email send · Platform Events/real-time triggers · config UI for ranking weights · Postgres checkpointing · ReAct/free-tool-choice agents · additional web sources beyond one live + cache · Slack approval surface · production multi-tenancy · any change to the in-org package's no-callout invariant.
