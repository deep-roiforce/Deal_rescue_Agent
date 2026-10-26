"""End-to-end behaviour through the node functions (Phase 1 DoD)."""

from __future__ import annotations

import json
from pathlib import Path

from deal_rescue.settings import Settings, ToolMode
from tests.conftest import (
    DEMO_DATE,
    FILLER_ACCOUNT,
    FILLER_ID,
    MERIDIAN_ACCOUNT,
    MERIDIAN_ID,
)


def _settings(tmp_path: Path, fixtures_dir: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        tool_mode=ToolMode.FAKE,
        as_of=DEMO_DATE,
        state_dir=tmp_path / "runs",
        fixtures_dir=fixtures_dir,
        **overrides,
    )


def test_meridian_golden_record(settings, run_pipeline, golden):
    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    assert state["status"] == "published"
    assert state["validation_errors"] == []
    assert state["retries"] == 1
    assert state["synthesis"]["milestones"] == golden["milestones"]
    assert state["synthesis"]["table_data"] == golden["table_data"]
    assert state["synthesis"]["deal_score"] == golden["deal_score"]
    assert state["synthesis"]["evidence_level"] == "full"
    assert state["replay_url"] == f"/briefs/{MERIDIAN_ID}", "the human-readable brief"
    assert state["story_url"].startswith(settings.storymydata_base_url)
    assert state["writeback"]["opportunity_updated"] is True
    # one audit record per web item + one for the transcript
    assert len(state["writeback"]["audit_task_ids"]) == 4


def test_score_is_not_authored_by_the_model(settings, run_pipeline):
    """base_deterministic comes from the rubric, never from the agent (D6/D9)."""
    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    assert state["score_base"]["base"] == 40
    assert state["synthesis"]["deal_score"]["base_deterministic"] == 40
    assert state["synthesis"]["deal_score"]["value"] == 34


def test_thin_evidence_path(settings, run_pipeline):
    """No web, no transcript -> shorter org-grounded email + flag (D11)."""
    state = run_pipeline(settings, FILLER_ID, FILLER_ACCOUNT)

    assert state["status"] == "published"
    assert state["web_findings"]["found"] is False
    assert state["transcript"]["found"] is False
    assert state["synthesis"]["evidence_level"] == "org_only"
    assert state["synthesis"]["email_draft"]["low_context_flag"] is True
    assert len(state["synthesis"]["email_draft"]["body"]) < 900
    assert state["synthesis"]["deal_score"]["llm_adjustment"] == 0
    assert state["writeback"]["audit_task_ids"] == []


def test_enrichment_failure_does_not_kill_the_run(settings, run_pipeline, monkeypatch):
    """D4: external sources are enrichment, not dependencies.

    Both enrichment tools blow up; the run still publishes, just thinner.
    """

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    from deal_rescue.tools.transcript import fake as transcript_fake
    from deal_rescue.tools.web_research import fake as web_fake

    monkeypatch.setattr(web_fake.FakeWebResearch, "search", boom)
    monkeypatch.setattr(transcript_fake.FakeTranscript, "fetch_latest", boom)

    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    assert state["status"] == "published"
    assert state["web_findings"]["found"] is False
    assert "provider down" in state["web_findings"]["reason"]
    assert state["transcript"]["found"] is False
    assert state["synthesis"]["evidence_level"] == "org_only"


def test_missing_org_data_ends_the_run(settings, run_pipeline):
    state = run_pipeline(settings, "006DOESNOTEXIST1", "Nowhere Inc")

    assert state["status"] == "failed_fetch_org"
    assert state["synthesis"] is None
    assert state["replay_url"] is None


def test_validation_failure_retries_then_passes(tmp_path, fixtures_dir, run_pipeline, golden):
    """The gate rejects an invented date, hands the reason back, and the second
    attempt publishes (D7)."""
    settings = _settings(tmp_path, fixtures_dir, agentforce_fake_fault="invented_date")

    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    assert state["status"] == "published"
    assert state["retries"] == 2
    assert state["validation_errors"] == []
    assert state["synthesis"]["milestones"] == golden["milestones"]


def test_invented_source_also_recovers(tmp_path, fixtures_dir, run_pipeline):
    settings = _settings(tmp_path, fixtures_dir, agentforce_fake_fault="invented_source")

    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    assert state["status"] == "published"
    assert state["retries"] == 2


def test_unfixable_output_fails_closed(tmp_path, fixtures_dir, run_pipeline):
    """Refusing to publish is a successful outcome of the design."""
    settings = _settings(tmp_path, fixtures_dir, agentforce_fake_fault="permanent")

    state = run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    assert state["status"] == "failed_validation"
    assert state["retries"] == settings.max_synth_retries + 1
    assert state["replay_url"] is None
    assert any("matches no web finding" in err for err in state["validation_errors"])


def test_publish_writes_an_inspectable_story_payload(settings, run_pipeline):
    run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    stories = list((Path(settings.state_dir) / "stories").glob("*.json"))
    assert len(stories) == 1

    body = json.loads(stories[0].read_text(encoding="utf-8"))
    assert body["table"].splitlines()[0] == "Period\tStage progress\tAmount"
    assert len(body["milestones"]) == 6
    assert all("rowIndex" in m for m in body["milestones"])


def test_writeback_payload_is_persisted(settings, run_pipeline):
    run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)

    path = Path(settings.state_dir) / "writebacks" / f"{MERIDIAN_ID}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["score"] == 34
    assert payload["email_draft"]["to_name"] == "Ray Gutierrez"
    assert {finding["source"] for finding in payload["audit_findings"]} == {
        "web:people_change_2026-08-20",
        "web:expansion_pr_2026-09-02",
        "web:jobs_estimating_supervisor",
        "transcript:2026-07-14",
    }
