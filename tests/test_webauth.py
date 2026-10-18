"""Website-style sign-in: state lifecycle and where logins land."""

from __future__ import annotations

import pytest

from deal_rescue import gdrive, profiles, sfdc, webauth
from deal_rescue.settings import Settings


def _settings(tmp_path, **overrides) -> Settings:
    defaults = dict(_env_file=None, credentials_dir=tmp_path / "creds",
                    sf_client_id="CID", google_client_id="GCID",
                    google_client_secret="GSEC")
    defaults.update(overrides)
    return Settings(**defaults)


def _state_of(url: str) -> str:
    return url.split("state=")[1].split("&")[0]


def test_start_parks_state_and_builds_the_web_redirect(tmp_path):
    settings = _settings(tmp_path)

    url = webauth.salesforce_start(settings, "http://localhost:8765/")

    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fauth%2Fsalesforce%2Fcallback" in url
    assert _state_of(url) in webauth.PENDING


def test_a_state_is_single_use(tmp_path):
    """A replayed callback must never reach a second token exchange."""
    settings = _settings(tmp_path)
    state = _state_of(webauth.salesforce_start(settings, "http://localhost:8765/"))

    webauth._redeem(state, "salesforce")

    with pytest.raises(webauth.WebAuthError, match="already used"):
        webauth._redeem(state, "salesforce")


def test_a_state_cannot_cross_providers(tmp_path):
    settings = _settings(tmp_path, deal_rescue_user="a@b.c")
    state = _state_of(webauth.google_start(settings, "http://localhost:8765/"))

    with pytest.raises(webauth.WebAuthError):
        webauth._redeem(state, "salesforce")


def test_google_requires_a_salesforce_identity_first(tmp_path):
    with pytest.raises(webauth.WebAuthError, match="Salesforce first"):
        webauth.google_start(_settings(tmp_path), "http://localhost:8765/")


def test_salesforce_finish_lands_in_a_profile(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(webauth, "update_env", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webauth.sfdc, "exchange_login_code",
        lambda s, code, verifier, redirect_override=None: {
            "access_token": "AT", "refresh_token": "RT",
            "instance_url": "https://x.my.salesforce.com",
        },
    )
    monkeypatch.setattr(
        webauth.sfdc, "userinfo",
        lambda url, token: {"name": "Pat Example", "preferred_username": "Pat@example.com"},
    )

    state = _state_of(webauth.salesforce_start(settings, "http://localhost:8765/"))
    email = webauth.salesforce_finish(settings, "CODE", state)

    assert email == "pat@example.com"
    assert profiles.load(settings, email)["salesforce"]["refresh_token"] == "RT"


def test_google_finish_attaches_to_the_active_user(tmp_path, monkeypatch):
    settings = _settings(tmp_path, deal_rescue_user="pat@example.com")
    profiles.save(settings, "pat@example.com", salesforce={"refresh_token": "RT"})
    monkeypatch.setattr(webauth, "update_env", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webauth.gdrive, "exchange_login_code",
        lambda s, code, verifier, redirect_override=None: {
            "access_token": "AT", "refresh_token": "GRT",
        },
    )
    monkeypatch.setattr(webauth.gdrive, "google_userinfo",
                        lambda token: {"email": "pat.personal@example.com"})

    state = _state_of(webauth.google_start(settings, "http://localhost:8765/"))
    webauth.google_finish(settings, "CODE", state)

    record = profiles.load(settings, "pat@example.com")
    assert record["google"]["refresh_token"] == "GRT"
    assert record["salesforce"]["refresh_token"] == "RT", "the SF login must survive"


def test_status_reports_what_the_header_needs(tmp_path):
    settings = _settings(tmp_path, deal_rescue_user="pat@example.com")
    profiles.save(settings, "pat@example.com",
                  salesforce={"refresh_token": "RT"},
                  google={"refresh_token": "GRT", "email": "x@gmail.com"})

    report = webauth.status(settings)

    assert report["salesforce_connected"] and report["google_connected"]
    assert report["google_account"] == "x@gmail.com"
    assert report["google_configured"] is True
