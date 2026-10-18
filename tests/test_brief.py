"""The rescue brief: publish's human-readable deliverable."""

from __future__ import annotations

import pytest

from deal_rescue.brief import brief_url, render_brief, save_brief
from tests.conftest import MERIDIAN_ACCOUNT, MERIDIAN_ID


@pytest.fixture
def published(settings, run_pipeline):
    return run_pipeline(settings, MERIDIAN_ID, MERIDIAN_ACCOUNT)


def test_publish_writes_a_real_openable_brief(settings, published):
    path = settings.state_dir / "briefs" / f"{MERIDIAN_ID}.html"

    assert published["brief_path"] == str(path)
    assert path.exists(), "the brief is a real file, not an animation-only artifact"
    assert published["replay_url"] == brief_url(MERIDIAN_ID)


def test_brief_tells_the_whole_story(settings, published):
    page = render_brief(published, settings)

    assert "Meridian Fabrication" in page
    assert "$240,000" in page
    assert "Why this deal stalled" in page
    assert "How it could be saved" in page
    assert "DRAFT — NOT SENT" in page, "the email is a draft, never a send"
    assert published["synthesis"]["email_draft"]["to_name"] in page
    assert "transcript:2026-07-14" in page, "citations survive into the brief"


def test_brief_carries_the_models_full_read(settings, published):
    page = render_brief(published, settings)

    assert "The full read — how to rescue this deal" in page
    assert published["synthesis"]["rescue_report"].splitlines()[0] in page
    assert "Written by the model" in page, "model-authored text is labeled"
    assert "The Salesforce record" in page
    assert "Contact roles" in page and "Field history" in page


def test_brief_escapes_model_text(settings, published):
    published["synthesis"]["email_draft"]["subject"] = '<script>alert("x")</script>'

    page = render_brief(published, settings)

    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_brief_refuses_an_unsafe_deal_id(settings, published):
    published["deal_id"] = "../../etc/passwd"

    with pytest.raises(ValueError, match="safe filename"):
        save_brief(published, settings)
