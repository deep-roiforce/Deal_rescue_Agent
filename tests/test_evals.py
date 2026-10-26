"""The eval harness: the gate as grader, retries counted the graph's way."""

from __future__ import annotations

import json

from deal_rescue.evals import categorize, format_table, load_cases, run_eval, save_report


def test_fake_backend_passes_every_case_first_try(settings):
    report = run_eval(settings)

    assert report["summary"]["passed"] == report["summary"]["total"]
    assert report["summary"]["first_pass_rate"] == 1.0
    assert report["summary"]["violations"] == {}


def test_cases_cover_the_properties_the_demo_depends_on(settings):
    names = {case.name for case in load_cases(settings)}

    assert "meridian_full_evidence" in names
    assert "meridian_org_only" in names
    # the departed-champion trap exists and names the trap
    trap = next(c for c in load_cases(settings) if c.name == "meridian_web_only")
    assert "dana kowalski" in trap.forbidden_recipients


def test_a_self_correcting_fault_fails_first_try_then_passes(settings):
    faulty = settings.model_copy(update={"agentforce_fake_fault": "invented_date"})

    report = run_eval(faulty)

    assert report["summary"]["passed"] == report["summary"]["total"]
    assert report["summary"]["first_pass_rate"] == 0.0
    assert report["summary"]["violations"].get("invented_date")


def test_a_permanent_fault_fails_closed_after_the_retry_budget(settings):
    broken = settings.model_copy(update={"agentforce_fake_fault": "permanent"})

    report = run_eval(broken)

    assert report["summary"]["passed"] == 0
    for result in report["results"]:
        assert result["attempts_used"] == 1 + settings.max_synth_retries


def test_report_is_saved_for_cross_provider_diffing(settings):
    report = run_eval(settings)
    save_report(report, settings)

    saved = json.loads((settings.state_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert saved["summary"] == report["summary"]


def test_table_renders_every_case(settings):
    report = run_eval(settings)

    table = format_table(report)

    for result in report["results"]:
        assert result["case"] in table


def test_error_categories_map_to_the_gate_vocabulary():
    assert categorize("schema: milestones.0.date: field required") == "schema"
    assert categorize("milestone 'X': external date 2026-08-05 matches no web finding []") == "invented_date"
    assert categorize("email_draft.to_contact_id '' is not a contact role on this opportunity []") == "recipient"
    assert categorize("source 'web:linkedin' was not among the inputs provided to synthesis") == "ungrounded_source"
    assert categorize("something novel") == "other"
