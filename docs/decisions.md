# Locked decisions → where they live in code

The spec locks twelve decisions. A decision that isn't enforced anywhere is just
a slide, so each one below names the code that makes it true and the test that
keeps it true.

| # | Decision | Enforced in | Tested by |
|---|---|---|---|
| D1 | Pull-based daily shortlist, not real-time | `shortlist.py` (batch, outside the graph) | `test_shortlist.py` |
| D2 | Human picks the deal | `shortlist.resolve_deal`, `POST /rescue` | `test_shortlist.py::test_resolve_*` |
| D3 | Three fetchers run in parallel | `graph.py` — three `START →` edges, one fan-in | `test_graph.py::test_fetchers_fan_out_from_start` |
| D4 | Graceful degradation; org data is the floor | `nodes/fetch_web.py`, `nodes/fetch_transcript.py`, `tools/base.never_raise`, `nodes/assemble.route_after_assemble` | `test_pipeline.py::test_enrichment_failure_does_not_kill_the_run`, `::test_missing_org_data_ends_the_run` |
| D5 | One synthesis step holds all judgment; reads are plain tools. *Amended 2026-10-17:* the backend is provider-pluggable — Anthropic API (default) or Agentforce — because the demo org has no Agentforce license. Prompt, merge fields and gate are identical across providers (`SYNTHESIS_PROVIDER`) | `tools/agentforce/`, `nodes/synthesize.py`, `settings.synthesis_provider` | `tests/tools/test_agentforce.py`, `tests/tools/test_agentforce_anthropic.py` |
| D6 | LLM never touches numbers | `tools/agentforce/prompt.py` (grounding set) + `validation.py` (re-checked) | `test_validation.py` — invented date / amount / table row |
| D7 | Schema validation gate, retry ≤2 | `nodes/validate.py`, `validation.py` | `test_pipeline.py::test_validation_failure_retries_then_passes`, `::test_unfixable_output_fails_closed` |
| D8 | No external email send; approval + send native | no send code exists; `salesforce_writeback` writes a draft Task with an approval flag | `tests/tools/test_salesforce_writeback.py::test_draft_task_starts_unapproved` |
| D9 | Deterministic rubric core + bounded LLM adjustment | `scoring.py` computes it; `assemble` passes it in; `validation.py` re-checks it | `test_scoring.py`, `test_validation.py::test_rewritten_base_score_is_rejected` |
| D10 | LangGraph, deterministic, no free-roaming agents | `graph.py` — fixed nodes and edges, no tool-choosing agent | `test_graph.py::test_graph_compiles_with_the_expected_nodes` |
| D11 | Thin-evidence rule | `SynthesisRequest.evidence_level`, `validation.py` org_only checks, fake's org-only path | `test_pipeline.py::test_thin_evidence_path`, `test_validation.py::test_org_only_*` |
| D12 | Ranking = `amount × stall_days`, configurable by design, no UI | `scoring.stall_rank`, `settings.ScoreWeights` | `test_shortlist.py::test_ranking_is_amount_times_stall_days`, `test_scoring.py::test_weights_are_configurable` |

## The two rules that carry the demo

**D6 — the LLM selects, labels and annotates. It does not compute.**
Every date, amount, stage name and contact id the agent may use is handed to it
in `build_merge_fields()`, and every one it returns is checked against org data
in `validate_synthesis()`. The prompt and the gate are two statements of the same
rule; `tests/test_validation.py` is where they are held to each other.

**D7 — the gate, not the agent, decides what gets published.**
A run that ends `failed_validation` published nothing and said why. That is the
outcome the design is *for*. `AGENTFORCE_FAKE_FAULT=permanent` demonstrates it
without a live agent.

## The eval harness holds the synthesis backend to the rules

`python -m deal_rescue.cli eval` (`evals.py`) runs fixture-grounded cases
through the configured backend with the graph's own retry discipline and grades
them with the validation gate itself — plus expectations the gate cannot see,
like "never address the departed champion". Swap `SYNTHESIS_PROVIDER` /
`SYNTHESIS_MODEL`, re-run, diff `.runs/eval_report.json`. Its first run caught
the fake replaying the golden record on partial evidence.

## Reopening a decision

Don't, without changing the spec first. If the spec changes: update the row
above, the enforcing code, and the test in the same commit. (D5's provider
amendment, 2026-10-17, followed this path: the org has no Agentforce license,
so the transport became pluggable while the prompt/gate contract stayed locked.)
