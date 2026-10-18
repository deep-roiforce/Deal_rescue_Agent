# Tool: `agentforce`

The synthesis step — merge + judgment (D5, amended). One contract,
`synthesize_rescue(...)`, and this is the **only** place an LLM touches the
pipeline. The live backend is provider-pluggable: the same prompt, merge fields
and validation gate drive whichever transport supplies the judgment.

| | |
|---|---|
| Transport | `SYNTHESIS_PROVIDER=anthropic` → Claude via the Anthropic API (default); `agentforce` → MCP wrapper around the Agentforce Agent API |
| Consumed by | node `synthesize` (fan-in target) |
| Degrades? | **No.** But malformed output is a *validation failure*, not an exception |
| Live phase | 2.4 |
| Mode env | `AGENTFORCE_MODE` (falls back to `TOOL_MODE`) |

## Contract

```python
from deal_rescue.tools.agentforce import get_tool, SynthesisRequest
tool = get_tool()

tool.synthesize_rescue(SynthesisRequest(
    org_data=...,        # verbatim from fetch_org — the grounding set
    web_findings=...,    # may be {found: false}
    transcript=...,      # may be {found: false}
    score_base=...,      # deterministic rubric result from scoring.py
    prior_errors=[...],  # empty first pass; validation errors on retry
)) -> dict   # raw, unvalidated SynthesisOutput-shaped JSON
```

The tool returns raw JSON on purpose. `deal_rescue.validation` is the gate —
"the agent said so" is not acceptance (D7).

## Why the deterministic score is an *input*

D9: the orchestrator computes `base_deterministic` from the rubric and hands it
to the agent. The agent may move it by ±15 and must cite a signal for any nonzero
move. The gate re-computes the base and rejects output that disagrees. The LLM
never produces the number (D6).

## The prompt template lives in `prompt.py`

`build_merge_fields()` is the grounding set — `ALLOWED_STAGE_DATES`,
`ALLOWED_WEB_DATES`, `ALLOWED_MEETING_DATES`, `ALLOWED_AMOUNTS`,
`ALLOWED_CONTACT_IDS`, `ALLOWED_SOURCES`, `SCORE_BASE`. Every hard rule in
`INSTRUCTIONS` maps to a check in `validation.py`. If you edit one, edit both —
`tests/test_validation.py` is where they meet.

Keeping `INSTRUCTIONS` in the repo means the org-side prompt template is
reviewable in git rather than only in Setup.

## Modes

**fake** — Meridian returns the golden record with the score re-grounded on the
live rubric output (so the fixture can't drift from `scoring.py`). Every other
account gets a genuine org-only synthesis: stage milestones, a short factual
email, `low_context_flag: true`, `evidence_level: "org_only"` (D11).

Fault injection for demoing the gate — set `AGENTFORCE_FAKE_FAULT` to:

| value | effect |
|---|---|
| `invented_date` | adds an external milestone dated 2026-08-05 with no web item behind it → rejected, retried, passes on attempt 2 |
| `invented_source` | cites `web:linkedin_scrape_2026-08-20`, which was never fetched → rejected, then passes |
| `permanent` | never self-corrects → run ends `failed_validation` after 2 retries |

**live, provider `anthropic` (default)** — `pip install -e ".[synthesis]"`, set
`ANTHROPIC_API_KEY` in `.env`, `AGENTFORCE_MODE=live`. One `messages.create`
per attempt: `INSTRUCTIONS` goes in the system prompt (cached between retries),
the grounded INPUT payload is the user message, and the reply is parsed with
`extract_json()`. A safety-classifier refusal is rescued server-side
(`fallbacks="default"`); a refusal that survives the fallback raises instead of
burning the retry budget. `SYNTHESIS_MODEL` overrides the model
(default `claude-opus-5-5`).

**live, provider `agentforce`** (Phase 2.4, transport not wired) — build the MCP
wrapper exposing `synthesize_rescue`, point `AGENTFORCE_MCP_URL` at it, set
`AGENTFORCE_AGENT_ID`, `SYNTHESIS_PROVIDER=agentforce`. The org-side agent setup
guide is `salesforce/agentforce/AGENT_SETUP.md`.

`VERIFY-IN-REPO` (spec §4.2 N6): reuse the existing Agent API client from the
prompt-template project if one exists rather than writing a second one.

## Evals

`python -m deal_rescue.cli eval` (`deal_rescue/evals.py`) runs fixture-grounded
cases through the configured backend with the graph's own retry discipline and
grades them with the validation gate — plus expectations the gate cannot see
(never address the departed champion; org-only must be flagged). `--runs N`
repeats each case for nondeterministic backends; the report also lands in
`.runs/eval_report.json` so two providers or models can be diffed.

## Tests

`tests/tools/test_agentforce.py`

- Meridian fake reproduces the golden record byte-exactly
- fake re-grounds `base_deterministic` on the rubric, not the fixture
- unknown account yields `evidence_level: "org_only"` + `low_context_flag: true`
- each fault produces output the gate rejects
- `extract_json()` survives code fences, leading prose, and returns None on junk
- `build_merge_fields()` exposes no date or amount absent from org data
