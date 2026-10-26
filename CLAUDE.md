# Deal Rescue Agent — Claude instructions

## Read first

`docs/architecture.md` and `docs/decisions.md` before any implementation. The
build spec (`deal-rescue-agent-spec.md`) is the source of truth for *what*; those
two docs map it onto *where in the code*. Architecture is LOCKED — implement as
specified, raise blockers, do not invent alternatives.

## Locked decisions (do not reopen)

- Orchestrator is **LangGraph**, deterministic: fixed nodes and edges, no
  free-roaming ReAct agent
- **One synthesis step holds all judgment.** Reads go through plain MCP tools.
  Backend is provider-pluggable (`SYNTHESIS_PROVIDER`): Anthropic API default,
  Agentforce optional — same prompt, same merge fields, same gate either way
- **The LLM never touches numbers.** Dates, amounts, stage names pass through
  deterministically; the agent selects, labels, annotates
- **The gate decides what publishes**, not the agent — schema + grounding checks,
  retry ≤ 2, then fail closed
- **Deal score = deterministic rubric + bounded LLM adjustment** (±15, must cite
  a signal)
- **No email send anywhere in this codebase.** Draft → approval flag → Flow →
  Salesforce sends natively
- **Enrichment never fails the run.** Web and transcript may be empty; org data
  is the floor
- Three fetchers run **in parallel**
- Shortlist ranking is `amount × stall_days`, configurable by constant, no UI

## Conventions

- One tool = one package under `src/deal_rescue/tools/<name>/` with exactly:
  `contract.py`, `fake.py`, `live.py`, `tool.py`, `README.md`
- Nodes import `contract` and `tool.get_tool()` — never `fake` or `live` directly
- One node = one file under `src/deal_rescue/nodes/`, a plain
  `(state, settings) -> partial state` function
- `settings.py` is the only module that reads the environment
- Every new tool gets a `ToolSpec` in `tools/__init__.py`, its own README, and
  `tests/tools/test_<name>.py`
- Every prompt rule in `tools/agentforce/prompt.py` needs a matching check in
  `validation.py`. Edit them together
- Changing a score weight or a fixture changes the golden record — update
  `fixtures/meridian/synthesis_golden.json` and the tests in the same commit

## Commands

```bash
pip install -e ".[graph,api,dev]"   # Python 3.11+
python -m deal_rescue.cli setup     # first run: Salesforce browser login + Tavily key
pytest                              # honesty rules first, arithmetic second
python -m deal_rescue.cli shortlist
python -m deal_rescue.cli rescue meridian
uvicorn deal_rescue.api:app --reload
AGENTFORCE_FAKE_FAULT=permanent python -m deal_rescue.cli rescue meridian   # show the gate
```

## Do not

- Add an email send path of any kind (no Gmail, no SMTP, no external send)
- Let an LLM produce a date, an amount, a stage name or the base score
- Skip the validation gate, or widen it to make an agent's output pass
- Add Platform Events, a ranking-weights UI, Postgres checkpointing, or a second
  live web source
- Reach into `fake.py` or `live.py` from a node
- Change the in-org Deal Replay package's no-callout invariant
- Combine multiple build phases into one session
