from __future__ import annotations

from deal_rescue.tools.transcript import get_tool, select_excerpts
from deal_rescue.tools.transcript.live import meeting_date_from_title, parse_transcript_text


def test_meridian_transcript_is_found(settings):
    result = get_tool(settings).fetch_latest("Meridian Fabrication")

    assert result["found"] is True
    assert result["meeting_date"] == "2026-07-14"
    assert len(result["excerpts"]) == 4
    assert result["excerpts"][0]["speaker"] == "Dana Kowalski"


def test_unknown_account_degrades_instead_of_raising(settings):
    result = get_tool(settings).fetch_latest("Wabash Tool & Die")

    assert result["found"] is False
    assert "no transcript Doc found" in result["reason"]


def test_parse_attributes_speakers():
    lines = parse_transcript_text(
        "Dana Kowalski: Let me socialize this internally.\n"
        "Ray Gutierrez: Turnaround is the problem."
    )

    assert lines == [
        {"speaker": "Dana Kowalski", "text": "Let me socialize this internally."},
        {"speaker": "Ray Gutierrez", "text": "Turnaround is the problem."},
    ]


def test_parse_folds_continuation_lines():
    lines = parse_transcript_text("Dana Kowalski: Let me check\nwith finance first.")

    assert lines == [{"speaker": "Dana Kowalski", "text": "Let me check with finance first."}]


def test_parse_keeps_unattributed_openers():
    lines = parse_transcript_text("Recording started.\nRay Gutierrez: Morning.")

    assert lines[0] == {"speaker": None, "text": "Recording started."}


def test_excerpt_selection_keeps_only_intent_lines():
    lines = [
        {"speaker": "A", "text": "Good morning everyone."},
        {"speaker": "B", "text": "Budget is confirmed for FY27."},
        {"speaker": "A", "text": "Nice weather."},
        {"speaker": "B", "text": "Quote turnaround is our pain."},
    ]

    picked = select_excerpts(lines)

    assert [e.text for e in picked] == [
        "Budget is confirmed for FY27.",
        "Quote turnaround is our pain.",
    ]


def test_excerpt_selection_respects_the_limit():
    lines = [{"speaker": "A", "text": "budget line"} for _ in range(20)]

    assert len(select_excerpts(lines, limit=3)) == 3


def test_meeting_date_from_doc_title():
    assert meeting_date_from_title(
        "Meridian <> Solution Review - 2026-07-14 - Transcript"
    ).isoformat() == "2026-07-14"
    assert meeting_date_from_title("Untitled transcript") is None
