"""The every-24-hours component (D1): the shortlist refreshes itself."""

from __future__ import annotations

from deal_rescue.api import refresh_shortlist_once
from deal_rescue.settings import Settings
from deal_rescue.shortlist import load_shortlist


def test_one_scheduled_batch_rebuilds_and_persists(settings):
    count = refresh_shortlist_once(settings)

    entries = load_shortlist(settings)
    assert count == len(entries) > 0
    assert (settings.state_dir / "shortlist.json").exists()


def test_the_interval_defaults_to_daily_and_zero_disables():
    assert Settings(_env_file=None).shortlist_refresh_hours == 24.0
    assert Settings(_env_file=None, shortlist_refresh_hours=0).shortlist_refresh_hours == 0
