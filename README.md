# Deal Rescue Agent

**An LLM agent that cannot publish a hallucination.**

Deal Rescue takes one stalled Salesforce opportunity, gathers everything knowable
about it — the CRM record, outside-world signals, the latest meeting transcript
from Google Drive — and has Claude write the rescue: a scored timeline, a full
read of the deal, and an email draft. Then a deterministic **grounding gate**
re-checks every date, amount, contact and citation against what was actually
fetched. Output that invents anything is rejected with reasons, retried at most
twice, and then the run **fails closed, publishing nothing**.

The thesis: in front of a CRM, *groundedness is enforced by code; only judgment
is delegated to the model.*

```
             fetch_org ┐
             fetch_web ┼─▶ assemble ─▶ synthesize ─▶ validate ─┬─▶ publish ─▶ rescue brief + Salesforce draft
       fetch_transcript┘   (rubric,     (Claude)     (the gate) └─▶ retry ≤2 ─▶ END failed_validation
                            no LLM)
```

## The claims this codebase keeps — and how

**The LLM never touches a number.** The deal score is a deterministic rubric
(`scoring.py`: start at 100, deduct for silence, close-date pushes, stage
regressions, declining activity). Claude may adjust it ±15 and must cite a
signal for any nonzero move. Every date, amount, stage name and contact id the
model may use is handed to it as a closed grounding set
(`tools/agentforce/prompt.py`) and re-derived + re-checked on the way out
(`validation.py`). Every prompt rule has a matching gate check; the tests hold
them to each other.

**The gate decides what publishes, not the agent.** Watch it fail closed:

```bash
AGENTFORCE_FAKE_FAULT=permanent python -m deal_rescue.cli rescue meridian
```

**No email is ever sent from this codebase.** Publish writes a *draft* with an
approval flag; a human approves inside Salesforce and Salesforce sends natively.

**The model is swappable because the guardrails are the product.** Synthesis
runs against the Anthropic API by default (`SYNTHESIS_PROVIDER` /
`SYNTHESIS_MODEL`); the same prompt, merge fields and gate hold Opus, Sonnet
and Haiku to one standard — and the built-in eval proves which models clear it.

## Try it in two minutes — no keys, no org

Python 3.11+. Fake mode runs the entire pipeline on fixtures:

```bash
pip install -e ".[graph,api,dev]"
pytest                                   # 241 tests: honesty rules first
python -m deal_rescue.cli rescue meridian
uvicorn deal_rescue.api:app --port 8765  # then open http://localhost:8765
```

The dashboard shows the run live: each node's actual output streams into an
"inner workings" feed (the rubric math line by line, the transcript quotes,
Claude's draft and its cited adjustment), the gate node opens into its full
rulebook with this run's allowlists, and every published run leaves a
human-readable **rescue brief** at `/briefs/{deal_id}` — the deal, the evidence,
momentum vs. risks, and the model's full rescue plan on one page.

## Going live

`http://localhost:8765/setup` is a guided setup page: paste a Salesforce
External Client App consumer key, a Google OAuth client (read-only Drive, for
meeting transcripts), a Tavily key (web research) and an Anthropic key — each
saved write-only into `.env`, each tool flipping live independently. Enrichment
is allowed to come back empty; org data is the only hard dependency.

## Hardening — reviewed and enforced

Points an external review would probe, answered in code rather than in docs:

- **SOQL injection**: no user input reaches SOQL today (every interpolated Id
  comes from our own query results), and as defense in depth every record Id is
  allowlist-validated (`sfdc.soql_id`, 15/18 base-62 chars) before it may enter
  a query string.
- **Zero-tolerance gate, tested adversarially**: a draft citing **$240,001**
  against a $240,000 record, or a milestone shifted by **one day**, fails
  validation — `tests/test_validation.py` pins both, alongside invented dates,
  amounts, recipients, citations and tampered tables.
- **Timeout discipline**: every outbound HTTP call shares two explicit budgets
  (`HTTP_TIMEOUT`, 30 s read / 10 s connect; `_LONG` 60 s for SOQL pagination
  and Doc export) — constants, not configuration, so they cannot be
  misconfigured away.
- **Retry loop is provably bounded**: the attempt counter increments in exactly
  one node, malformed JSON counts as an attempt, state overwrites rather than
  accumulates (no list reducers), and the fail-closed ceiling is pinned by test.
- **Apex runs `WITH USER_MODE`**: every query in the in-org scoring classes
  enforces the running user's FLS and sharing; tests create their own data
  (no `SeeAllData`).
- **Telemetry can't hurt the pipeline**: the run log never raises into a run
  (tested), and enrichment failures degrade with reasons instead of aborting —
  org data is the only hard dependency.
- **Known limit, stated**: the departed-recipient check matches full names in
  news snippets; a nickname can slip past it. That errs toward a false
  negative, never a false rejection — recipients themselves are matched by
  contact ID, not name (documented at the check in `validation.py`).

## Evals and the run log

```bash
python -m deal_rescue.cli eval       # fixture cases, graded by the gate itself
python -m deal_rescue.cli history    # every run: model, outcome, retries, score, timing
```

The eval harness reuses the validation gate as its grader and adds expectations
the gate can't see (never email the departed champion). Its first run caught a
real bug. Every rescue and eval case lands in a SQLite run log
(`.runs/deal_rescue.db`) — per-model pass rates, attempts and latency are a
`GROUP BY`, which is how Sonnet and Haiku were certified against Opus here.

## Layout

```
src/deal_rescue/
  graph.py        LangGraph wiring          state.py      graph state
  nodes/          one file per node         tools/        one package per integration
  scoring.py      deterministic rubric      validation.py the gate
  schemas.py      output contract           settings.py   the only reader of env
  evals.py        gate-graded eval suite    runlog.py     SQLite run telemetry
  brief.py        the published rescue brief
  shortlist.py    daily batch + resolution  api.py / cli.py  surfaces
web/              dashboard + setup page (single files, no build step)
fixtures/         Meridian golden record, curated demo evidence
tests/            honesty rules first, arithmetic second
docs/             architecture · decisions · tools · configuration · runbook
```

## The six tools

Each is a self-contained package — contract, fake, live adapter, mode switch,
README — so any one can be changed without touching the graph.

| Tool | Does | Degrades? |
|---|---|---|
| [`salesforce_reads`](src/deal_rescue/tools/salesforce_reads/README.md) | Opportunity, history, contacts, activities | no — the floor |
| [`web_research`](src/deal_rescue/tools/web_research/README.md) | Expansion / people-change / jobs signals | yes |
| [`transcript`](src/deal_rescue/tools/transcript/README.md) | Latest meeting transcript from Drive, excerpted | yes |
| [`agentforce`](src/deal_rescue/tools/agentforce/README.md) | The one judgment call (Anthropic API or Agentforce) | no |
| [`storymydata`](src/deal_rescue/tools/storymydata/README.md) | Enriched Deal Replay (Phase 2.5) | no |
| [`salesforce_writeback`](src/deal_rescue/tools/salesforce_writeback/README.md) | Score, draft, brief URL, audit tasks (Phase 2.6) | no |

## Where the rest is written down

| | |
|---|---|
| What it does and where the code is | [docs/architecture.md](docs/architecture.md) |
| The locked decisions, and what enforces each | [docs/decisions.md](docs/decisions.md) |
| Tool index + how to add one | [docs/tools.md](docs/tools.md) |
| Org-side build: fields, Flow, permission set | [docs/salesforce-app.md](docs/salesforce-app.md) |
| Every environment variable | [docs/configuration.md](docs/configuration.md) |
| Install, run, demo, go-live order | [docs/runbook.md](docs/runbook.md) |
