from __future__ import annotations

import json

from deal_rescue.tools.storymydata import (
    build_table,
    get_tool,
    row_index_for,
    stage_ordinal,
    synthesis_to_story_request,
)


def test_stage_ordinal_follows_the_pipeline():
    assert stage_ordinal("Discovery") == 2
    assert stage_ordinal("Negotiation") == 5
    assert stage_ordinal("Something Custom") == 1


def test_table_is_tsv_with_amounts_formatted(golden):
    table = build_table(golden["table_data"]).splitlines()

    assert table[0] == "Period\tStage progress\tAmount"
    assert table[1] == "2026-03-04\t2\t$240,000"
    assert len(table) == 6  # header + 5 stage rows


def test_table_shows_the_regression_as_a_drop(golden):
    values = [int(line.split("\t")[1]) for line in build_table(golden["table_data"]).splitlines()[1:]]

    assert values == [2, 3, 4, 5, 4]  # Negotiation -> Proposal


def test_row_index_exact_match():
    dates = ["2026-03-04", "2026-06-10", "2026-08-22"]

    assert row_index_for("2026-06-10", dates) == 1.0


def test_row_index_interpolates_between_rows():
    dates = ["2026-01-01", "2026-01-11"]

    assert row_index_for("2026-01-06", dates) == 0.5


def test_row_index_clamps_outside_the_range():
    dates = ["2026-03-04", "2026-08-22"]

    assert row_index_for("2020-01-01", dates) == 0.0
    assert row_index_for("2030-01-01", dates) == 1.0


def test_row_index_on_empty_table():
    assert row_index_for("2026-03-04", []) is None


def test_meridian_maps_to_a_story_request(golden, org_data):
    request = synthesis_to_story_request(golden, org_data)

    assert request.shape == "long"
    assert request.description == "Meridian Fabrication - Plant 2 Quoting System Replacement"
    assert len(request.milestones) == 6
    assert all(m.row_index is not None for m in request.milestones)
    assert all(0.0 <= m.row_index <= 4.0 for m in request.milestones)


def test_external_milestone_lands_between_stage_rows(golden, org_data):
    request = synthesis_to_story_request(golden, org_data)
    departure = next(m for m in request.milestones if "departed" in m.title)

    # 2026-08-20 sits between the 6/10 (index 3) and 8/22 (index 4) rows
    assert 3.0 < departure.row_index < 4.0


def test_api_body_uses_the_engine_field_names(golden, org_data):
    body = synthesis_to_story_request(golden, org_data).to_api()

    assert set(body) >= {"table", "description", "milestones", "shape", "template"}
    assert set(body["milestones"][0]) == {"period", "title", "desc", "rowIndex"}


def test_fake_persists_the_payload_and_returns_a_stable_url(settings, golden, org_data):
    tool = get_tool(settings)
    request = synthesis_to_story_request(golden, org_data)

    first = tool.create_story(request)
    second = tool.create_story(request)

    assert first.url == second.url
    assert first.ok is True

    saved = list((settings.state_dir / "stories").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text(encoding="utf-8"))["description"].startswith("Meridian")
