"""The run log: every rescue and eval lands in SQLite, queryably."""

from __future__ import annotations

import json

from deal_rescue import runlog
from deal_rescue.evals import run_eval, save_report
from tests.conftest import MERIDIAN_ACCOUNT, MERIDIAN_ID


def test_a_pipeline_run_is_recorded(settings, run_pipeline):
    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)
    runlog.record_rescue(state, settings, seconds=12.34)

    (run,) = runlog.recent(settings)
    assert run["kind"] == "rescue"
    assert run["account"] == MERIDIAN_ACCOUNT
    assert run["status"] == "published"
    assert run["score"] == state["synthesis"]["deal_score"]["value"]
    assert run["model"] == settings.synthesis_model
    assert run["seconds"] == 12.34
    assert json.loads(run["errors"]) == []


def test_an_eval_lands_one_row_per_case(settings):
    report = run_eval(settings)
    save_report(report, settings)

    rows = [r for r in runlog.recent(settings, limit=50) if r["kind"] == "eval"]
    assert len(rows) == len(report["results"])
    assert all(row["status"] == "pass" for row in rows)


def test_stats_aggregate_by_model(settings, run_pipeline):
    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)
    runlog.record_rescue(state, settings, seconds=10.0)
    runlog.record_rescue(state, settings, seconds=20.0)

    (agg,) = runlog.stats(settings)
    assert agg["runs"] == 2
    assert agg["ok"] == 2
    assert agg["avg_seconds"] == 15.0


def test_telemetry_failure_never_kills_a_run(settings, monkeypatch):
    monkeypatch.setattr(runlog, "_connect", lambda s: (_ for _ in ()).throw(OSError("disk")))

    runlog.record_rescue({"deal_id": "x"}, settings, seconds=1.0)  # must not raise
    runlog.record_eval({"results": [{}]}, settings)  # must not raise
