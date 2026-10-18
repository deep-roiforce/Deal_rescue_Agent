"""Synthesis eval harness.

The validation gate is an objective grader, so the eval reuses it: every case is
a frozen `SynthesisRequest` with a known-correct outcome, and the score is
whether the configured synthesis backend (fake, Anthropic, Agentforce) produces
output the gate accepts -- plus a few per-case expectations the gate does not
cover, like "never address the departed champion by name".

The runner mirrors the graph's retry loop (attempt, feed the errors back,
retry <= `max_synth_retries`) so "passes after self-correction" is measured the
same way the pipeline experiences it.

    python -m deal_rescue.cli eval            # table
    python -m deal_rescue.cli eval --runs 3   # repeat each case; LLMs vary
    python -m deal_rescue.cli eval --json     # full report

The report also lands in `.runs/eval_report.json` for diffing across providers
or models: run once with SYNTHESIS_PROVIDER/SYNTHESIS_MODEL set one way, once
the other, and compare.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from deal_rescue.scoring import compute_base_score
from deal_rescue.settings import Settings
from deal_rescue.tools.agentforce import SynthesisRequest, get_tool
from deal_rescue.validation import validate_synthesis

# gate-message substring -> violation category (for the report's tally)
ERROR_CATEGORIES = (
    ("schema:", "schema"),
    ("is not a JSON object", "parse"),
    ("stage date", "invented_date"),
    ("external date", "invented_date"),
    ("meeting date", "invented_date"),
    ("table_data", "table_mismatch"),
    ("to_contact_id", "recipient"),
    ("email_draft addresses", "recipient"),
    ("amount", "invented_amount"),
    ("deal_score", "score"),
    ("source ", "ungrounded_source"),
    ("evidence_level", "evidence_level"),
    ("org_only", "evidence_level"),
)


def categorize(error: str) -> str:
    for needle, category in ERROR_CATEGORIES:
        if needle in error:
            return category
    return "other"


@dataclass
class EvalCase:
    name: str
    request: SynthesisRequest
    # names (lowercased) the email must never be addressed to
    forbidden_recipients: list[str] = field(default_factory=list)
    expect_low_context: bool = False


def _meridian_request(settings: Settings, *, web: bool, transcript: bool) -> SynthesisRequest:
    fixtures = settings.fixtures_dir / "meridian"
    org = json.loads((fixtures / "org_data.json").read_text(encoding="utf-8"))
    breakdown = compute_base_score(
        org, settings.today(), settings.score, settings.stage_order()
    )
    return SynthesisRequest(
        org_data=org,
        web_findings=(
            json.loads((fixtures / "web_findings.json").read_text(encoding="utf-8"))
            if web else {"found": False, "items": []}
        ),
        transcript=(
            json.loads((fixtures / "transcript.json").read_text(encoding="utf-8"))
            if transcript else {"found": False}
        ),
        score_base=breakdown.as_dict(),
    )


def load_cases(settings: Settings) -> list[EvalCase]:
    """Fixture-grounded cases. Each one encodes a property the demo depends on."""
    return [
        # Full evidence: org + web + transcript. The headline path.
        EvalCase(
            name="meridian_full_evidence",
            request=_meridian_request(settings, web=True, transcript=True),
            # Meridian's web findings say Dana Kowalski left for Halstead.
            # Emailing her -- the exact failure the gate caught live -- is the
            # one mistake this case exists to punish.
            forbidden_recipients=["dana kowalski"],
        ),
        # The departed-champion trap without the transcript softening it.
        EvalCase(
            name="meridian_web_only",
            request=_meridian_request(settings, web=True, transcript=False),
            forbidden_recipients=["dana kowalski"],
        ),
        # D11: both enrichment sources empty. Short, factual, flagged.
        EvalCase(
            name="meridian_org_only",
            request=_meridian_request(settings, web=False, transcript=False),
            expect_low_context=True,
        ),
        # Transcript but no web: still "full" evidence, no external milestones
        # are permitted (ALLOWED_WEB_DATES is empty).
        EvalCase(
            name="meridian_transcript_only",
            request=_meridian_request(settings, web=False, transcript=True),
            forbidden_recipients=[],
        ),
    ]


def _check_expectations(case: EvalCase, synthesis: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    draft = synthesis.get("email_draft") or {}
    to_name = str(draft.get("to_name") or "").strip().lower()
    for forbidden in case.forbidden_recipients:
        if to_name == forbidden:
            failures.append(f"email addressed to {draft.get('to_name')!r}, who has departed")
    if case.expect_low_context and not draft.get("low_context_flag"):
        failures.append("expected low_context_flag=true on an org_only case")
    return failures


def run_case(case: EvalCase, settings: Settings) -> dict[str, Any]:
    """One case through the graph's attempt/retry discipline."""
    tool = get_tool(settings)
    max_attempts = 1 + settings.max_synth_retries
    attempts: list[dict[str, Any]] = []
    request = case.request.model_copy(update={"prior_errors": []})
    passed = False
    expectation_failures: list[str] = []
    started = time.monotonic()

    for attempt in range(1, max_attempts + 1):
        synthesis = tool.synthesize_rescue(request)
        errors = validate_synthesis(synthesis, request, settings.score)
        attempts.append({
            "attempt": attempt,
            "parsed": "_raw" not in synthesis,
            "errors": errors,
            "categories": sorted({categorize(e) for e in errors}),
        })
        if not errors:
            passed = True
            expectation_failures = _check_expectations(case, synthesis)
            break
        request = request.model_copy(update={"prior_errors": errors})

    return {
        "case": case.name,
        "passed": passed and not expectation_failures,
        "gate_passed": passed,
        "first_pass": passed and len(attempts) == 1,
        "attempts_used": len(attempts),
        "expectation_failures": expectation_failures,
        "attempts": attempts,
        "seconds": round(time.monotonic() - started, 2),
    }


def run_eval(settings: Settings, runs: int = 1) -> dict[str, Any]:
    cases = load_cases(settings)
    results = [run_case(case, settings) for case in cases for _ in range(runs)]

    total = len(results)
    violations: dict[str, int] = {}
    for result in results:
        for attempt in result["attempts"]:
            for category in attempt["categories"]:
                violations[category] = violations.get(category, 0) + 1

    report = {
        "provider": settings.synthesis_provider,
        "model": settings.synthesis_model,
        "mode": settings.mode_for("agentforce").value,
        "runs_per_case": runs,
        "results": results,
        "summary": {
            "total": total,
            "passed": sum(r["passed"] for r in results),
            "pass_rate": round(sum(r["passed"] for r in results) / total, 3) if total else 0.0,
            "first_pass_rate": (
                round(sum(r["first_pass"] for r in results) / total, 3) if total else 0.0
            ),
            "violations": dict(sorted(violations.items())),
        },
    }
    return report


def save_report(report: dict[str, Any], settings: Settings) -> None:
    from deal_rescue import runlog

    settings.state_dir.mkdir(parents=True, exist_ok=True)
    path = settings.state_dir / "eval_report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    runlog.record_eval(report, settings)


def format_table(report: dict[str, Any]) -> str:
    lines = [
        f"synthesis eval -- mode={report['mode']} provider={report['provider']} "
        f"model={report['model']} (x{report['runs_per_case']} per case)",
        "",
        f"  {'case':34s} {'gate':6s} {'first try':9s} {'attempts':8s} notes",
    ]
    for result in report["results"]:
        notes = "; ".join(
            result["expectation_failures"]
            or (result["attempts"][-1]["errors"][:1] if not result["gate_passed"] else [])
        )
        lines.append(
            f"  {result['case']:34s} "
            f"{'PASS' if result['passed'] else 'FAIL':6s} "
            f"{'yes' if result['first_pass'] else 'no':9s} "
            f"{result['attempts_used']:<8d} {notes[:70]}"
        )
    summary = report["summary"]
    lines += [
        "",
        f"  pass rate {summary['pass_rate']:.0%}  "
        f"first-try {summary['first_pass_rate']:.0%}  "
        f"({summary['passed']}/{summary['total']})",
    ]
    if summary["violations"]:
        tally = ", ".join(f"{k}={v}" for k, v in summary["violations"].items())
        lines.append(f"  violations seen: {tally}")
    return "\n".join(lines)
