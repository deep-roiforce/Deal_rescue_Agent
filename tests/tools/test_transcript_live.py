"""The live transcript adapter: Google auth shapes and Drive mapping.

No network anywhere -- the Drive client is monkeypatched at its seams, the
same way the Salesforce transport is tested.
"""

from __future__ import annotations

import pytest

from deal_rescue import gdrive
from deal_rescue.settings import Settings
from deal_rescue.tools.transcript.curated import curated_transcript
from deal_rescue.tools.transcript.live import LiveTranscript


def _settings(**overrides) -> Settings:
    from deal_rescue.settings import REPO_ROOT

    defaults = dict(_env_file=None, fixtures_dir=REPO_ROOT / "fixtures",
                    google_client_id="GCID", google_client_secret="GSEC",
                    google_refresh_token="GRT")
    defaults.update(overrides)
    return Settings(**defaults)


# --- auth URL ----------------------------------------------------------------
def test_google_authorize_url_asks_for_an_offline_readonly_grant():
    url = gdrive.authorize_url(_settings(), "CHAL", "ST8")

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "drive.readonly" in url
    assert "access_type=offline" in url, "without this there is no refresh token"
    assert "prompt=consent" in url, "without this a re-login returns no refresh token"
    assert "code_challenge_method=S256" in url
    assert "state=ST8" in url


def test_google_exchange_without_a_refresh_token_fails_with_the_fix(monkeypatch):
    monkeypatch.setattr(gdrive, "_token_request", lambda data: {"access_token": "AT"})

    with pytest.raises(gdrive.GoogleAuthError, match="myaccount.google.com/permissions"):
        gdrive.exchange_login_code(_settings(), "CODE", "VER")


# --- Drive query building ------------------------------------------------------
def test_find_doc_builds_a_scoped_escaped_query(monkeypatch):
    captured = {}

    class FakeResponse:
        def json(self):
            return {"files": [{"id": "F1", "name": "Doc"}]}

    def fake_get(self, url, params=None):
        captured.update(params or {})
        return FakeResponse()

    monkeypatch.setattr(gdrive.DriveClient, "_get", fake_get)
    client = gdrive.DriveClient(_settings(google_drive_folder_id="FOLDER9"))

    doc = client.find_doc("O'Brien & Sons")

    assert doc == {"id": "F1", "name": "Doc"}
    q = captured["q"]
    assert "name contains 'O\\'Brien & Sons'" in q, "quotes must be escaped"
    assert "'FOLDER9' in parents" in q
    assert "application/vnd.google-apps.document" in q
    assert captured["orderBy"] == "modifiedTime desc"


# --- Drive first, curated as the safety net ------------------------------------
def test_curated_transcript_exists_for_meridian():
    s = _settings()
    assert curated_transcript(s.fixtures_dir, "Meridian Fabrication")["found"] is True
    assert curated_transcript(s.fixtures_dir, "Northgate Stamping") is None


def test_a_staged_drive_doc_beats_the_curated_transcript(monkeypatch):
    """The demo meetings are staged as real Docs; live runs must read them."""
    monkeypatch.setattr(
        gdrive.DriveClient, "find_doc",
        lambda self, name: {"id": "DRIVE1",
                            "name": "Meridian Fabrication <> Review 2026-07-14 - Transcript"},
    )
    monkeypatch.setattr(
        gdrive.DriveClient, "export_text",
        lambda self, file_id: "Dana Kowalski: Budget approval is the next step.\n",
    )

    result = LiveTranscript(_settings()).fetch_latest("Meridian Fabrication")

    assert result["found"] is True
    assert result["doc_id"] == "DRIVE1", "Drive wins when the Doc exists"


def test_curated_covers_meridian_when_drive_is_empty(monkeypatch):
    monkeypatch.setattr(gdrive.DriveClient, "find_doc", lambda self, name: None)

    result = LiveTranscript(_settings()).fetch_latest("Meridian Fabrication")

    assert result["found"] is True
    assert result["meeting_date"] == "2026-07-14"


def test_curated_covers_meridian_when_drive_is_unreachable(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("Drive is down")

    monkeypatch.setattr(gdrive.DriveClient, "_get", explode)

    result = LiveTranscript(_settings()).fetch_latest("Meridian Fabrication")

    assert result["found"] is True
    assert result["meeting_date"] == "2026-07-14"


# --- the real-account path -----------------------------------------------------
def test_live_fetch_parses_a_staged_doc(monkeypatch):
    monkeypatch.setattr(
        gdrive.DriveClient, "find_doc",
        lambda self, name: {"id": "DOC9",
                            "name": "Northgate <> Review - 2026-09-15 - Transcript"},
    )
    monkeypatch.setattr(
        gdrive.DriveClient, "export_text",
        lambda self, file_id: (
            "Recording started.\n"
            "Pat Lee: Budget is approved for this quarter.\n"
            "and we want a pilot before December.\n"
            "Pat Lee: Nice weather today.\n"
        ),
    )

    result = LiveTranscript(_settings()).fetch_latest("Northgate Stamping")

    assert result["found"] is True
    assert result["doc_id"] == "DOC9"
    assert result["meeting_date"] == "2026-09-15"
    texts = [e["text"] for e in result["excerpts"]]
    assert texts == ["Budget is approved for this quarter. and we want a pilot before December."]


def test_live_degrades_when_no_doc_matches(monkeypatch):
    monkeypatch.setattr(gdrive.DriveClient, "find_doc", lambda self, name: None)

    result = LiveTranscript(_settings()).fetch_latest("Northgate Stamping")

    assert result["found"] is False
    assert "no transcript Doc" in result["reason"]


def test_live_degrades_without_a_google_login():
    result = LiveTranscript(_settings(google_refresh_token=None)).fetch_latest(
        "Northgate Stamping"
    )

    assert result["found"] is False
    assert "cli setup" in result["reason"]


# --- the service-account path (the "simple option") ---------------------------
def test_service_account_key_grants_a_drive_token(tmp_path, monkeypatch):
    import json

    key = tmp_path / "sa.json"
    key.write_text(json.dumps({
        "client_email": "deal-rescue-reader@proj.iam.gserviceaccount.com",
        "private_key": "UNUSED-IN-TEST",
    }), encoding="utf-8")

    captured = {}
    monkeypatch.setattr(gdrive.jwt, "encode",
                        lambda claims, k, algorithm: captured.update(claims) or "ASSERTION")
    monkeypatch.setattr(gdrive, "_token_request",
                        lambda data: {"access_token": "SA-AT"})

    client = gdrive.DriveClient(_settings(google_refresh_token=None,
                                          google_credentials_path=key))
    client._ensure_token()

    assert client._token == "SA-AT"
    assert captured["iss"] == "deal-rescue-reader@proj.iam.gserviceaccount.com"
    assert captured["scope"].endswith("drive.readonly"), "read-only, always"


def test_a_user_login_beats_the_key_file(tmp_path, monkeypatch):
    """If both exist, the person's own login is the identity that acts."""
    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(gdrive, "_token_request",
                        lambda data: seen.update(data) or {"access_token": "AT"})

    client = gdrive.DriveClient(_settings(google_credentials_path=key))
    client._ensure_token()

    assert seen["grant_type"] == "refresh_token"


def test_not_a_key_file_fails_with_directions(tmp_path):
    key = tmp_path / "sa.json"
    key.write_text('{"type": "authorized_user"}', encoding="utf-8")

    client = gdrive.DriveClient(_settings(google_refresh_token=None,
                                          google_credentials_path=key))
    with pytest.raises(gdrive.GoogleAuthError, match="Service Accounts"):
        client._ensure_token()


def test_no_login_and_no_key_degrades_with_both_options(tmp_path):
    result = LiveTranscript(_settings(google_refresh_token=None)).fetch_latest(
        "Northgate Stamping"
    )

    assert result["found"] is False
    assert "cli setup" in result["reason"]
    assert "GOOGLE_CREDENTIALS_PATH" in result["reason"]
