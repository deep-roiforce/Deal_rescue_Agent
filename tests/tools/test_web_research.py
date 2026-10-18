from __future__ import annotations

from deal_rescue.tools.base import never_raise
from deal_rescue.tools.web_research import get_tool, slugify
from deal_rescue.tools.web_research.live import classify, make_id, normalize, parse_date


def test_meridian_returns_classified_signals(settings):
    findings = get_tool(settings).search("Meridian Fabrication")

    assert findings["found"] is True
    assert len(findings["items"]) == 3
    assert {item["signal_type"] for item in findings["items"]} == {
        "people_change",
        "expansion",
        "jobs",
    }


def test_item_ids_are_stable_citation_keys(settings):
    findings = get_tool(settings).search("Meridian Fabrication")
    ids = [item["id"] for item in findings["items"]]

    assert "expansion_pr_2026-09-02" in ids
    assert ids == [item["id"] for item in get_tool(settings).search("Meridian Fabrication")["items"]]


def test_unknown_account_degrades_instead_of_raising(settings):
    findings = get_tool(settings).search("Wabash Tool & Die")

    assert findings["found"] is False
    assert findings["items"] == []
    assert "no cached web results" in findings["reason"]


def test_slugify_handles_ampersands():
    assert slugify("Wabash Tool & Die") == "wabash-tool-and-die"
    assert slugify("Meridian Fabrication") == "meridian-fabrication"


def test_normalize_drops_unusable_rows_and_dedupes():
    items = normalize(
        [
            {"title": "A", "url": "https://x/1", "content": "expansion news"},
            {"title": "", "url": "https://x/2"},
            {"title": "C", "url": ""},
            {"title": "A again", "url": "https://x/1"},
        ]
    )

    assert [item.title for item in items] == ["A"]


def test_classification_of_signal_wording():
    assert classify("Acme announces plant expansion", "") == "expansion"
    assert classify("Jane Doe appointed COO", "") == "people_change"
    assert classify("Acme is hiring an Estimator", "") == "jobs"
    assert classify("Acme quarterly update", "routine") == "news"


def test_date_parsing_is_tolerant():
    assert parse_date("2026-09-02T10:00:00Z").isoformat() == "2026-09-02"
    assert parse_date("not a date") is None
    assert parse_date(None) is None


def test_make_id_is_slug_plus_date():
    assert make_id("Meridian announces Plant 3 expansion", parse_date("2026-09-02")) == (
        "meridian-announces-plant-3_2026-09-02"
    )


def test_never_raise_turns_any_failure_into_a_degraded_payload():
    """The contract the live adapter ships with (D4)."""

    @never_raise("web search failed")
    def boom():
        raise RuntimeError("provider down")

    assert boom() == {
        "found": False,
        "items": [],
        "reason": "web search failed: RuntimeError: provider down",
    }


# --- regressions found by running the provider for real ---------------------
def test_tavily_news_dates_are_rfc_2822():
    """The news topic returns RFC 2822, not ISO.

    Taking text[:10] and parsing ISO gave 'Wed, 15 J' -> None, which silently
    cost every external milestone: the gate checks a milestone's date against
    the dates actually fetched, so undated findings ground nothing.
    """
    from deal_rescue.tools.web_research.live import parse_date

    assert parse_date("Wed, 15 Jul 2026 00:00:00 GMT").isoformat() == "2026-07-15"
    assert parse_date("Thu, 04 Aug 2026 12:30:00 +0000").isoformat() == "2026-08-04"


def test_iso_dates_still_parse():
    from deal_rescue.tools.web_research.live import parse_date

    assert parse_date("2026-09-02").isoformat() == "2026-09-02"
    assert parse_date("2026-09-02T10:00:00Z").isoformat() == "2026-09-02"
    assert parse_date("garbage") is None


def test_news_queries_ask_for_the_news_topic():
    """Only the news topic carries published_date; general returns none at all."""
    from deal_rescue.tools.web_research.contract import default_query_plan

    plan = dict((q, t) for q, t in default_query_plan("Meridian Fabrication"))
    topics = list(plan.values())

    assert topics.count("news") == 2, "news and expansion queries must use topic=news"
    assert "general" in topics, "job postings are not news and carry no date"


def test_publisher_is_derived_from_the_url():
    """The audit Task says 'clarionledger.com', not just a URL."""
    from deal_rescue.tools.web_research.live import source_of

    assert source_of("https://www.prnewswire.com/news/x") == "prnewswire.com"
    assert source_of("https://ir.steeldynamics.com/press") == "ir.steeldynamics.com"
    assert source_of("not a url") is None


def test_investment_no_longer_means_expansion():
    """A stock-tip article is not an expansion signal. Real result, real bug."""
    from deal_rescue.tools.web_research.live import classify

    assert classify("How Much a $1000 Investment in Acme Made 10 Years Ago", "") == "news"
    assert classify("Acme announces plant expansion", "") == "expansion"


def test_executive_changes_are_people_changes():
    from deal_rescue.tools.web_research.live import classify

    assert classify("Jane Doe to become Acme's President and CEO", "") == "people_change"
    assert classify("Acme CFO steps down", "") == "people_change"


def test_live_search_prefers_curated_findings(settings, monkeypatch):
    """A fictional demo account must never be grounded on real articles about
    the wrong company -- live Tavily returned a footwear brand and a kiosk
    vendor for 'Meridian Fabrication'. Curated findings win; no network call."""
    from deal_rescue.settings import ToolMode
    from deal_rescue.tools.web_research.live import LiveWebResearch

    def explode(*args, **kwargs):
        raise AssertionError("curated account must not hit the provider")

    monkeypatch.setattr(LiveWebResearch, "_fetch", explode)
    live_settings = settings.model_copy(update={"web_mode": ToolMode.LIVE,
                                                "search_api_key": "tvly-x"})

    result = LiveWebResearch(live_settings).search("Meridian Fabrication")

    assert result["found"] is True
    assert any(i["id"] == "expansion_pr_2026-09-02" for i in result["items"])


def test_live_cache_writes_land_in_state_not_fixtures(settings):
    from deal_rescue.tools.web_research.live import LiveWebResearch

    adapter = LiveWebResearch(settings)

    assert str(settings.state_dir) in str(adapter.cache_dir)
    assert "fixtures" not in str(adapter.cache_dir)
