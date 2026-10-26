"""Google transport: user OAuth (PKCE) and the two Drive reads we need.

The transcript tool reads Google Meet transcripts out of Drive. Instead of a
service account -- a Cloud Console ceremony nobody enjoys -- the user logs into
their own Google account once during `cli setup`, with a READ-ONLY Drive scope,
and the stored refresh token does the rest. Nothing here can send mail, write a
file, or see anything the scope does not grant.

Plain REST via httpx; no Google SDK. Two endpoints is not a client library.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

from deal_rescue.settings import HTTP_TIMEOUT, HTTP_TIMEOUT_LONG, Settings
from deal_rescue.sfdc import generate_pkce_pair, wait_for_login_code  # shared loopback
from deal_rescue.tools.base import ToolError, ToolUnavailable
from urllib.parse import urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

CALLBACK_PATH = "/GoogleRedirect"
# drive.readonly: read files. openid email: so setup can say WHICH account.
SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"

__all__ = [
    "GoogleAuthError",
    "CALLBACK_PATH",
    "generate_pkce_pair",
    "wait_for_login_code",
    "authorize_url",
    "redirect_uri",
    "exchange_login_code",
    "google_userinfo",
    "DriveClient",
]


class GoogleAuthError(ToolError):
    """The Google login or token exchange failed."""


def redirect_uri(settings: Settings) -> str:
    return f"http://localhost:{settings.sf_callback_port}{CALLBACK_PATH}"


def authorize_url(
    settings: Settings, challenge: str, state: str, redirect_override: str | None = None
) -> str:
    if not settings.google_client_id:
        raise GoogleAuthError("GOOGLE_CLIENT_ID is not set")
    params = {
        "response_type": "code",
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_override or redirect_uri(settings),
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        # Without BOTH of these, Google omits the refresh token and the login
        # dies with the process.
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    try:
        response = httpx.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise GoogleAuthError(f"token request failed: {exc}") from exc
    try:
        return response.json()
    except ValueError:
        return {"error": f"HTTP {response.status_code}", "error_description": response.text[:200]}


def exchange_login_code(
    settings: Settings, code: str, verifier: str, redirect_override: str | None = None
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.google_client_id or "",
        "redirect_uri": redirect_override or redirect_uri(settings),
        "code_verifier": verifier,
    }
    # Google issues Desktop clients a "secret" that is not actually secret and
    # demands it at exchange even with PKCE.
    if settings.google_client_secret:
        data["client_secret"] = settings.google_client_secret

    payload = _token_request(data)
    if "access_token" not in payload:
        detail = payload.get("error_description") or payload.get("error") or "no detail"
        raise GoogleAuthError(f"Google code exchange failed: {detail}")
    if "refresh_token" not in payload:
        raise GoogleAuthError(
            "Google issued no refresh token. This usually means an earlier grant "
            "exists -- remove this app at https://myaccount.google.com/permissions "
            "and run setup again."
        )
    return payload


def google_userinfo(access_token: str) -> dict[str, Any]:
    response = httpx.get(
        USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT
    )
    if response.status_code != 200:
        raise GoogleAuthError(f"userinfo failed: HTTP {response.status_code}")
    return response.json()


def _service_account_grant(settings: Settings) -> dict[str, Any]:
    """Access token from a service-account key file -- the no-browser path.

    The simple sharing model: create a service account (no roles), download its
    JSON key, share the transcripts folder with the account's email as Viewer.
    No consent screen, no client id, no login; read-only scope as always.
    """
    key_path = Path(settings.google_credentials_path or "")
    if not key_path.exists():
        raise GoogleAuthError(f"service-account key not found at {key_path}")
    info = json.loads(key_path.read_text(encoding="utf-8"))
    for field in ("client_email", "private_key"):
        if field not in info:
            raise GoogleAuthError(
                f"{key_path.name} is not a service-account key (missing {field}) -- "
                "download the JSON key from IAM & Admin -> Service Accounts -> Keys"
            )

    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": info["client_email"],
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        info["private_key"],
        algorithm="RS256",
    )
    payload = _token_request(
        {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    )
    if "access_token" not in payload:
        detail = payload.get("error_description") or payload.get("error") or "no detail"
        raise GoogleAuthError(
            f"service-account token exchange failed: {detail}. Check that the Drive "
            "API is enabled in the key's project, and that the transcripts folder is "
            "shared with " + info.get("client_email", "the service account")
        )
    return payload


def service_account_email(settings: Settings) -> str | None:
    """Who to share the folder with, if a key file is configured."""
    try:
        key_path = Path(settings.google_credentials_path or "")
        if key_path.exists():
            return json.loads(key_path.read_text(encoding="utf-8")).get("client_email")
    except (OSError, ValueError):
        pass
    return None


class DriveClient:
    """The two Drive reads the transcript pipe needs, as the logged-in user."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: str | None = None
        self._minted_at = 0.0

    def _ensure_token(self) -> None:
        if self._token and (time.time() - self._minted_at) < 45 * 60:
            return
        settings = self.settings

        # Two ways in, fixed order: a person's stored login wins; a
        # service-account key file is the no-browser alternative.
        if not settings.google_refresh_token:
            if settings.google_credentials_path:
                payload = _service_account_grant(settings)
                self._token = payload["access_token"]
                self._minted_at = time.time()
                return
            raise ToolUnavailable(
                "no Google access configured -- run `python -m deal_rescue.cli setup` "
                "to log in, or set GOOGLE_CREDENTIALS_PATH to a service-account key"
            )

        data = {
            "grant_type": "refresh_token",
            "client_id": settings.google_client_id or "",
            "refresh_token": settings.google_refresh_token,
        }
        if settings.google_client_secret:
            data["client_secret"] = settings.google_client_secret
        payload = _token_request(data)
        if "access_token" not in payload:
            detail = payload.get("error_description") or payload.get("error") or "no detail"
            raise GoogleAuthError(
                f"stored Google login no longer works ({detail}). "
                "Re-run `python -m deal_rescue.cli setup`."
            )
        self._token = payload["access_token"]
        self._minted_at = time.time()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        self._ensure_token()
        response = httpx.get(
            url, params=params,
            headers={"Authorization": f"Bearer {self._token}"}, timeout=HTTP_TIMEOUT_LONG,
        )
        if response.status_code != 200:
            raise ToolError(f"Drive request failed ({response.status_code}): {response.text[:200]}")
        return response

    def find_doc(self, name_contains: str) -> dict[str, Any] | None:
        """Most recently modified Google Doc whose name mentions the account,
        optionally confined to the configured folder."""
        safe = name_contains.replace("\\", "\\\\").replace("'", "\\'")
        clauses = [
            f"name contains '{safe}'",
            "mimeType = 'application/vnd.google-apps.document'",
            "trashed = false",
        ]
        if self.settings.google_drive_folder_id:
            clauses.append(f"'{self.settings.google_drive_folder_id}' in parents")

        payload = self._get(
            DRIVE_FILES_URL,
            params={
                "q": " and ".join(clauses),
                "orderBy": "modifiedTime desc",
                "pageSize": 1,
                "fields": "files(id,name,modifiedTime)",
            },
        ).json()
        files = payload.get("files", [])
        return files[0] if files else None

    def export_text(self, file_id: str) -> str:
        response = self._get(
            f"{DRIVE_FILES_URL}/{file_id}/export", params={"mimeType": "text/plain"}
        )
        return response.text

    def probe(self) -> None:
        """Setup-time check: can we see Drive at all?"""
        self._get(DRIVE_FILES_URL, params={"pageSize": 1, "fields": "files(id)"})
