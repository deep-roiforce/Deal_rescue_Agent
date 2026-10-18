"""Setup wizard: the .env editor, the PKCE plumbing, and the auth order."""

from __future__ import annotations

import base64
import hashlib

import pytest

from deal_rescue.settings import Settings
from deal_rescue.setup_wizard import mask, update_env
from deal_rescue.sfdc import (
    SalesforceAuthError,
    SalesforceClient,
    authorize_url,
    exchange_login_code,
    generate_pkce_pair,
    parse_callback,
)


# --- .env editing ------------------------------------------------------------
def test_update_env_replaces_only_the_named_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment that must survive\n"
        "TOOL_MODE=fake\n"
        "SF_MODE=fake\n"
        "SEARCH_API_KEY=\n",
        encoding="utf-8",
    )

    update_env(env, {"SF_MODE": "live", "SEARCH_API_KEY": "tvly-abc"})
    lines = env.read_text(encoding="utf-8").splitlines()

    assert "# a comment that must survive" in lines
    assert "TOOL_MODE=fake" in lines
    assert "SF_MODE=live" in lines
    assert "SEARCH_API_KEY=tvly-abc" in lines
    assert "SF_MODE=fake" not in lines


def test_update_env_appends_new_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TOOL_MODE=fake\n", encoding="utf-8")

    update_env(env, {"SF_REFRESH_TOKEN": "tok123"})
    text = env.read_text(encoding="utf-8")

    assert "SF_REFRESH_TOKEN=tok123" in text
    assert "added by `cli setup`" in text


def test_update_env_creates_a_missing_file(tmp_path):
    env = tmp_path / ".env"

    update_env(env, {"SF_MODE": "live"})

    assert env.read_text(encoding="utf-8").strip() == (
        "# --- added by `cli setup` ---\nSF_MODE=live"
    )


def test_mask_never_shows_a_whole_secret():
    assert mask(None) == "not set"
    assert mask("short") == "set"
    assert mask("tvly-dev-abcdefgh1234") == "...1234"


# --- PKCE --------------------------------------------------------------------
def test_pkce_challenge_is_the_hash_of_the_verifier():
    verifier, challenge = generate_pkce_pair()

    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    assert challenge == expected
    assert 43 <= len(verifier) <= 128  # RFC 7636 bounds
    assert "=" not in verifier and "=" not in challenge


def test_pkce_pairs_are_unique():
    assert generate_pkce_pair() != generate_pkce_pair()


def test_authorize_url_carries_the_required_parameters():
    settings = Settings(_env_file=None, sf_client_id="CLIENTID", sf_callback_port=1717)

    url = authorize_url(settings, "CHALLENGE", "STATE123")

    assert url.startswith("https://login.salesforce.com/services/oauth2/authorize?")
    assert "client_id=CLIENTID" in url
    assert "code_challenge=CHALLENGE" in url
    assert "code_challenge_method=S256" in url
    assert "state=STATE123" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A1717%2FOauthRedirect" in url


# --- the login callback --------------------------------------------------------
def test_callback_with_the_right_state_yields_the_code():
    assert parse_callback("/OauthRedirect?code=abc&state=S1", "S1") == "abc"


def test_callback_with_the_wrong_state_is_rejected():
    """A stale or forged redirect must not be exchanged for tokens."""
    with pytest.raises(SalesforceAuthError, match="state mismatch"):
        parse_callback("/OauthRedirect?code=abc&state=WRONG", "S1")


def test_callback_carrying_an_error_is_surfaced():
    with pytest.raises(SalesforceAuthError, match="denied"):
        parse_callback(
            "/OauthRedirect?error=access_denied&error_description=denied&state=S1", "S1"
        )


# --- auth order ----------------------------------------------------------------
def test_refresh_token_wins_over_jwt(monkeypatch):
    """A stored browser login is the chosen path; the certificate flow only
    runs when no refresh token exists."""
    seen: dict = {}

    def fake_token_request(self, data):
        seen.update(data)
        return {"access_token": "AT", "instance_url": "https://x.my.salesforce.com"}

    monkeypatch.setattr(SalesforceClient, "_token_request", fake_token_request)
    settings = Settings(_env_file=None, sf_client_id="CID", sf_refresh_token="RT")

    client = SalesforceClient(settings)
    client._ensure_token()

    assert seen["grant_type"] == "refresh_token"
    assert client.instance_url == "https://x.my.salesforce.com"


def test_broken_stored_login_says_rerun_setup(monkeypatch):
    monkeypatch.setattr(
        SalesforceClient, "_token_request",
        lambda self, data: {"error": "invalid_grant", "error_description": "expired"},
    )
    settings = Settings(_env_file=None, sf_client_id="CID", sf_refresh_token="RT")

    with pytest.raises(SalesforceAuthError, match="Re-run"):
        SalesforceClient(settings)._ensure_token()


def test_exchange_demands_a_refresh_token(monkeypatch):
    """A login that cannot survive a restart is not a completed setup."""
    monkeypatch.setattr(
        SalesforceClient, "_token_request",
        lambda self, data: {"access_token": "AT", "instance_url": "https://x"},
    )
    settings = Settings(_env_file=None, sf_client_id="CID")

    with pytest.raises(SalesforceAuthError, match="refresh token"):
        exchange_login_code(settings, "CODE", "VERIFIER")


def test_exchange_explains_a_client_secret_demand(monkeypatch):
    monkeypatch.setattr(
        SalesforceClient, "_token_request",
        lambda self, data: {"error": "invalid_client", "error_description": "bad client"},
    )
    settings = Settings(_env_file=None, sf_client_id="CID")

    with pytest.raises(SalesforceAuthError, match="SF_CLIENT_SECRET"):
        exchange_login_code(settings, "CODE", "VERIFIER")


def test_a_rotated_refresh_token_is_persisted(monkeypatch, tmp_path):
    """Orgs with token rotation invalidate the token on every use. Keeping the
    old one gives exactly one successful run, then 'expired' -- which is how
    this was discovered. The replacement must land back in .env."""
    from deal_rescue import envfile

    env = tmp_path / ".env"
    env.write_text("SF_MODE=live\nSF_REFRESH_TOKEN=OLD\n", encoding="utf-8")
    monkeypatch.setattr(envfile, "ENV_PATH", env)

    monkeypatch.setattr(
        SalesforceClient, "_token_request",
        lambda self, data: {
            "access_token": "AT",
            "refresh_token": "NEW",
            "instance_url": "https://x.my.salesforce.com",
        },
    )
    settings = Settings(_env_file=None, sf_client_id="CID", sf_refresh_token="OLD")

    SalesforceClient(settings)._ensure_token()

    assert settings.sf_refresh_token == "NEW", "in-process settings must rotate too"
    assert "SF_REFRESH_TOKEN=NEW" in env.read_text(encoding="utf-8")


def test_rotation_never_writes_someone_elses_env(monkeypatch, tmp_path):
    """The guard: only a file holding exactly the burned token is rewritten."""
    from deal_rescue import envfile

    env = tmp_path / ".env"
    env.write_text("SF_REFRESH_TOKEN=SOMETHING_ELSE\n", encoding="utf-8")
    monkeypatch.setattr(envfile, "ENV_PATH", env)

    monkeypatch.setattr(
        SalesforceClient, "_token_request",
        lambda self, data: {"access_token": "AT", "refresh_token": "NEW"},
    )
    settings = Settings(_env_file=None, sf_client_id="CID", sf_refresh_token="OLD")
    SalesforceClient(settings)._ensure_token()

    assert "SOMETHING_ELSE" in env.read_text(encoding="utf-8")
