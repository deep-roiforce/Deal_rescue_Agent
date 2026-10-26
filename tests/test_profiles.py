"""Per-user credential profiles: the store, the hydration, the rotation."""

from __future__ import annotations

import json

import pytest

from deal_rescue import profiles
from deal_rescue.settings import Settings
from deal_rescue.sfdc import SalesforceClient


def _settings(tmp_path, **overrides) -> Settings:
    defaults = dict(_env_file=None, credentials_dir=tmp_path / "creds")
    defaults.update(overrides)
    return Settings(**defaults)


def test_save_and_load_round_trip(tmp_path):
    settings = _settings(tmp_path)

    path = profiles.save(settings, "Pat@Example.com", name="Pat Example",
                         salesforce={"refresh_token": "RT1", "instance_url": "https://x"})

    assert path.name == "pat@example.com.json", "profiles are keyed case-insensitively"
    record = profiles.load(settings, "pat@example.com")
    assert record["name"] == "Pat Example"
    assert record["salesforce"]["refresh_token"] == "RT1"


def test_save_merges_sections_instead_of_replacing_the_profile(tmp_path):
    settings = _settings(tmp_path)
    profiles.save(settings, "a@b.c", salesforce={"refresh_token": "RT1"})

    profiles.save(settings, "a@b.c", google={"refresh_token": "GRT"})

    record = profiles.load(settings, "a@b.c")
    assert record["salesforce"]["refresh_token"] == "RT1", "salesforce login must survive"
    assert record["google"]["refresh_token"] == "GRT"


def test_apply_hydrates_settings_from_the_active_profile(tmp_path):
    settings = _settings(tmp_path, deal_rescue_user="a@b.c")
    profiles.save(settings, "a@b.c",
                  salesforce={"refresh_token": "RT1", "instance_url": "https://org-a",
                              "username": "a@b.c"},
                  google={"refresh_token": "GRT"})

    hydrated = profiles.apply(settings)

    assert hydrated.sf_refresh_token == "RT1"
    assert hydrated.sf_instance_url == "https://org-a"
    assert hydrated.google_refresh_token == "GRT"
    assert settings.sf_refresh_token is None, "original settings untouched"


def test_the_as_flag_beats_the_default_user(tmp_path):
    """Two people, one machine -- the whole point."""
    settings = _settings(tmp_path, deal_rescue_user="a@b.c")
    profiles.save(settings, "a@b.c", salesforce={"refresh_token": "RT-A"})
    profiles.save(settings, "b@b.c", salesforce={"refresh_token": "RT-B"})

    assert profiles.apply(settings).sf_refresh_token == "RT-A"
    assert profiles.apply(settings, "b@b.c").sf_refresh_token == "RT-B"


def test_asking_for_an_unknown_user_names_the_known_ones(tmp_path):
    settings = _settings(tmp_path)
    profiles.save(settings, "a@b.c", salesforce={"refresh_token": "RT-A"})

    with pytest.raises(FileNotFoundError, match="a@b.c"):
        profiles.apply(settings, "nobody@b.c")


def test_no_profile_means_settings_pass_through(tmp_path):
    """A .env-only or JWT-only configuration keeps working untouched."""
    settings = _settings(tmp_path, deal_rescue_user="ghost@b.c", sf_refresh_token="ENV-RT")

    assert profiles.apply(settings).sf_refresh_token == "ENV-RT"


def test_rotation_lands_in_the_right_profile(tmp_path, monkeypatch):
    """Token rotation again, now with two users: only the profile holding the
    burned token is rewritten."""
    settings = _settings(tmp_path, sf_client_id="CID", deal_rescue_user="a@b.c")
    profiles.save(settings, "a@b.c", salesforce={"refresh_token": "OLD-A"})
    profiles.save(settings, "b@b.c", salesforce={"refresh_token": "RT-B"})

    monkeypatch.setattr(
        SalesforceClient, "_token_request",
        lambda self, data: {"access_token": "AT", "refresh_token": "NEW-A",
                            "instance_url": "https://x"},
    )
    hydrated = profiles.apply(settings)
    SalesforceClient(hydrated)._ensure_token()

    assert profiles.load(settings, "a@b.c")["salesforce"]["refresh_token"] == "NEW-A"
    assert profiles.load(settings, "b@b.c")["salesforce"]["refresh_token"] == "RT-B"


def test_profile_files_are_valid_json_on_disk(tmp_path):
    settings = _settings(tmp_path)
    path = profiles.save(settings, "a@b.c", salesforce={"refresh_token": "RT"})

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["email"] == "a@b.c"
    assert "updated" in on_disk
