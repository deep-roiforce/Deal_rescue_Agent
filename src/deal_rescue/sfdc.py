"""Salesforce transport: JWT auth and SOQL.

Shared by both Salesforce tools, like `settings.py` is shared -- a tool owns
its contract and its mapping, not its own copy of an HTTP client.

Auth is the OAuth 2.0 JWT bearer flow: sign a short-lived assertion with the
private key, exchange it for an access token. No password, no client secret,
nothing long-lived on disk except the key itself, which never leaves the
machine.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import jwt

from deal_rescue.settings import HTTP_TIMEOUT, HTTP_TIMEOUT_LONG, Settings
from deal_rescue.tools.base import ToolError

# Access tokens last far longer than this; re-minting early is cheap insurance
# against a long run straddling an expiry.

# A Salesforce record Id: 15 or 18 base-62 characters, nothing else. Queries in
# this codebase interpolate Ids into SOQL, and every Id today comes from our own
# earlier query results -- this guard is defense in depth so a future call site
# that forwards user input cannot become an injection path.
SOQL_ID = re.compile(r"^[A-Za-z0-9]{15,18}$")


def soql_id(value: str) -> str:
    """Validate a record Id before it may enter a SOQL string."""
    if not SOQL_ID.match(value or ""):
        raise ValueError(f"not a Salesforce record Id: {value!r}")
    return value

TOKEN_TTL_SECONDS = 20 * 60
ASSERTION_TTL_SECONDS = 180


class SalesforceAuthError(ToolError):
    """The JWT exchange failed. Almost always configuration, not transport."""


class SalesforceClient:
    """Thin SOQL client. One instance per run; caches its access token."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: str | None = None
        self._instance_url: str | None = None
        self._minted_at: float = 0.0

    # --- auth --------------------------------------------------------------
    def _private_key(self) -> str:
        path = self.settings.sf_private_key_path
        if not path:
            raise SalesforceAuthError("SF_PRIVATE_KEY_PATH is not set")
        key_file = Path(path)
        if not key_file.exists():
            raise SalesforceAuthError(f"private key not found at {key_file}")
        return key_file.read_text(encoding="utf-8")

    def _mint_token(self) -> None:
        """Two ways in, tried in a fixed order.

        A refresh token (stored by `cli setup` after a browser login) wins when
        present -- it is the path a person chose. The JWT certificate flow is
        the headless alternative. No silent fallback between them: a broken
        refresh token should say "re-run setup", not quietly switch identities.
        """
        if self.settings.sf_refresh_token:
            payload = self._refresh_token_grant()
        else:
            payload = self._jwt_grant()

        self._token = payload["access_token"]
        self._instance_url = payload.get("instance_url") or self.settings.sf_instance_url
        self._minted_at = time.time()

    def _refresh_token_grant(self) -> dict[str, Any]:
        settings = self.settings
        if not settings.sf_client_id:
            raise SalesforceAuthError("SF_CLIENT_ID is not set")

        data = {
            "grant_type": "refresh_token",
            "client_id": settings.sf_client_id,
            "refresh_token": settings.sf_refresh_token,
        }
        if settings.sf_client_secret:
            data["client_secret"] = settings.sf_client_secret

        payload = self._token_request(data)
        if "access_token" not in payload:
            detail = payload.get("error_description") or payload.get("error") or "no detail"
            raise SalesforceAuthError(
                f"stored Salesforce login no longer works ({detail}). "
                "Re-run `python -m deal_rescue.cli setup` to log in again, or remove "
                "SF_REFRESH_TOKEN from .env to use the JWT certificate flow instead."
            )

        # Orgs with refresh-token ROTATION invalidate the token on every use
        # and issue a replacement in the same response. Failing to store that
        # replacement means exactly one successful run, then "expired" -- which
        # is how this branch was discovered. Persist it or lose the login.
        rotated = payload.get("refresh_token")
        if rotated and rotated != settings.sf_refresh_token:
            from deal_rescue.envfile import replace_refresh_token
            from deal_rescue.profiles import replace_sf_refresh_token

            old_token = settings.sf_refresh_token or ""
            # Profiles are the normal home; the .env fallback covers a
            # configuration that never ran the profile-era setup.
            if not replace_sf_refresh_token(settings, old_token, rotated):
                replace_refresh_token(old_token, rotated)
            settings.sf_refresh_token = rotated

        return payload

    def _jwt_grant(self) -> dict[str, Any]:
        settings = self.settings
        missing = [
            name
            for name, value in (
                ("SF_CLIENT_ID", settings.sf_client_id),
                ("SF_USERNAME", settings.sf_username),
            )
            if not value
        ]
        if missing:
            raise SalesforceAuthError(
                f"missing settings: {', '.join(missing)}. "
                "Easiest fix: run `python -m deal_rescue.cli setup`."
            )

        audience = settings.sf_login_url.rstrip("/")
        assertion = jwt.encode(
            {
                "iss": settings.sf_client_id,
                "sub": settings.sf_username,
                "aud": audience,
                "exp": int(time.time()) + ASSERTION_TTL_SECONDS,
            },
            self._private_key(),
            algorithm="RS256",
        )

        payload = self._token_request(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            }
        )

        if "access_token" not in payload:
            # Salesforce's JWT errors are terse; name the usual causes rather
            # than make the next person search for "invalid_grant".
            detail = payload.get("error_description") or payload.get("error") or "no detail"
            raise SalesforceAuthError(
                f"JWT exchange rejected: {detail}. "
                "Check that the certificate is uploaded to the External Client App, "
                "the user is pre-authorized for it, and SF_LOGIN_URL matches the org "
                "type (login.salesforce.com for production/developer, "
                "test.salesforce.com for sandboxes)."
            )
        return payload

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        """POST to the org's token endpoint; always returns the parsed body."""
        url = f"{self.settings.sf_login_url.rstrip('/')}/services/oauth2/token"
        try:
            response = httpx.post(url, data=data, timeout=HTTP_TIMEOUT)
        except httpx.HTTPError as exc:
            raise SalesforceAuthError(f"token request failed: {exc}") from exc
        try:
            return response.json()
        except ValueError:
            return {"error": f"HTTP {response.status_code}", "error_description": response.text[:200]}

    def _ensure_token(self) -> None:
        if self._token is None or (time.time() - self._minted_at) > TOKEN_TTL_SECONDS:
            self._mint_token()

    @property
    def instance_url(self) -> str:
        self._ensure_token()
        return (self._instance_url or "").rstrip("/")

    # --- SOQL --------------------------------------------------------------
    def query(self, soql: str) -> list[dict[str, Any]]:
        """Run SOQL, following pagination. Returns raw records."""
        self._ensure_token()
        version = self.settings.sf_api_version
        url = f"{self.instance_url}/services/data/v{version}/query"
        params: dict[str, Any] | None = {"q": soql}
        records: list[dict[str, Any]] = []

        while True:
            response = httpx.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=HTTP_TIMEOUT_LONG,
            )
            if response.status_code != 200:
                raise ToolError(
                    f"SOQL failed ({response.status_code}): {response.text[:300]}\n"
                    f"query: {soql}"
                )
            payload = response.json()
            records.extend(payload.get("records", []))

            next_url = payload.get("nextRecordsUrl")
            if payload.get("done", True) or not next_url:
                return records
            url = f"{self.instance_url}{next_url}"
            params = None


def flatten(record: dict[str, Any]) -> dict[str, Any]:
    """Drop SOQL's `attributes` noise and flatten one level of relationships.

    `Account.Name` arrives as `{"Account": {"Name": ...}}`; downstream code
    wants `Account.Name`.
    """
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == "attributes":
            continue
        if isinstance(value, dict) and "attributes" in value:
            for nested_key, nested_value in value.items():
                if nested_key != "attributes":
                    out[f"{key}.{nested_key}"] = nested_value
        else:
            out[key] = value
    return out


# --- interactive login (PKCE) -- used by `cli setup` -------------------------
#
# The browser flow a person actually completes: we open the org's login page,
# they sign in, Salesforce redirects to a tiny local server with a one-time
# code, and we trade that code (plus the PKCE verifier) for tokens. The refresh
# token is what gets stored -- no certificate, no password, no client secret.

CALLBACK_PATH = "/OauthRedirect"  # must match the app's registered callback URL
LOGIN_TIMEOUT_SECONDS = 900  # a first login involves finding credentials; 5 minutes was a stopwatch

_SUCCESS_HTML = b"""<!doctype html><meta charset="utf-8">
<title>Logged in</title>
<body style="font-family:system-ui;display:grid;place-items:center;height:90vh;background:#f6f7f8;color:#1a2027">
<div style="text-align:center"><div style="font-size:2.4rem">&#10003;</div>
<h2 style="margin:.3em 0">You're logged in</h2>
<p style="color:#5a6773">Deal Rescue has what it needs. You can close this tab<br>and return to the terminal.</p></div>"""

_FAILURE_HTML = b"""<!doctype html><meta charset="utf-8">
<title>Login failed</title>
<body style="font-family:system-ui;display:grid;place-items:center;height:90vh;background:#f6f7f8;color:#1a2027">
<div style="text-align:center"><div style="font-size:2.4rem">&#10007;</div>
<h2 style="margin:.3em 0">That didn't work</h2>
<p style="color:#5a6773">Return to the terminal for the reason and next step.</p></div>"""


def generate_pkce_pair() -> tuple[str, str]:
    """(verifier, challenge). The verifier stays local; only its SHA-256 goes
    into the login URL, so an intercepted redirect is useless without it."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def redirect_uri(settings: Settings) -> str:
    return f"http://localhost:{settings.sf_callback_port}{CALLBACK_PATH}"


def authorize_url(
    settings: Settings, challenge: str, state: str, redirect_override: str | None = None
) -> str:
    if not settings.sf_client_id:
        raise SalesforceAuthError("SF_CLIENT_ID is not set")
    params = {
        "response_type": "code",
        "client_id": settings.sf_client_id,
        "redirect_uri": redirect_override or redirect_uri(settings),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "api refresh_token",
        "state": state,
    }
    return f"{settings.sf_login_url.rstrip('/')}/services/oauth2/authorize?{urlencode(params)}"


def parse_callback(path: str, expected_state: str, callback_path: str = CALLBACK_PATH) -> str:
    """Extract the one-time code from the redirect, or raise with the reason."""
    parts = urlsplit(path)
    if parts.path != callback_path:
        raise SalesforceAuthError(f"unexpected callback path {parts.path!r}")
    params = dict(parse_qsl(parts.query))

    if params.get("state") != expected_state:
        raise SalesforceAuthError(
            "state mismatch on the login callback -- possibly a stale tab from an "
            "earlier attempt. Run setup again and use the freshly opened window."
        )
    if "error" in params:
        raise SalesforceAuthError(
            params.get("error_description") or params["error"]
        )
    code = params.get("code")
    if not code:
        raise SalesforceAuthError("login callback carried no code")
    return code


class _CallbackServer(HTTPServer):
    expected_state: str = ""
    callback_path: str = CALLBACK_PATH
    code: str | None = None
    failure: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- http.server API
        server: _CallbackServer = self.server  # type: ignore[assignment]
        if urlsplit(self.path).path != server.callback_path:
            self.send_response(404)
            self.end_headers()
            return
        try:
            server.code = parse_callback(self.path, server.expected_state, server.callback_path)
            body = _SUCCESS_HTML
        except SalesforceAuthError as exc:
            server.failure = str(exc)
            body = _FAILURE_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # silence request logging
        return


def wait_for_login_code(
    settings: Settings,
    expected_state: str,
    timeout_seconds: int = LOGIN_TIMEOUT_SECONDS,
    *,
    callback_path: str = CALLBACK_PATH,
) -> str:
    """Serve the callback URL until the browser delivers the code.

    Shared by the Salesforce and Google logins -- same loopback mechanics,
    different registered paths."""
    try:
        server = _CallbackServer(("localhost", settings.sf_callback_port), _CallbackHandler)
    except OSError as exc:
        raise SalesforceAuthError(
            f"could not listen on localhost:{settings.sf_callback_port} ({exc}). "
            "Something else is using the port -- close it, or set SF_CALLBACK_PORT "
            "and update the app's callback URL to match."
        ) from exc

    server.expected_state = expected_state
    server.callback_path = callback_path
    server.timeout = 1
    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline:
            server.handle_request()
            if server.code:
                return server.code
            if server.failure:
                raise SalesforceAuthError(server.failure)
    finally:
        server.server_close()
    raise SalesforceAuthError(
        f"no login completed within {timeout_seconds // 60} minutes -- run setup again"
    )


def exchange_login_code(
    settings: Settings, code: str, verifier: str, redirect_override: str | None = None
) -> dict[str, Any]:
    """One-time code + verifier -> access token, refresh token, instance URL.

    The redirect_uri must byte-match the one used at authorize time, so a web
    flow passes the same override to both calls."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.sf_client_id or "",
        "redirect_uri": redirect_override or redirect_uri(settings),
        "code_verifier": verifier,
    }
    if settings.sf_client_secret:
        data["client_secret"] = settings.sf_client_secret

    payload = SalesforceClient(settings)._token_request(data)
    if "access_token" not in payload:
        detail = payload.get("error_description") or payload.get("error") or "no detail"
        hint = ""
        if "secret" in detail.lower() or payload.get("error") == "invalid_client":
            hint = (
                " The app may be demanding a client secret: either untick "
                "'Require Secret for Web Server Flow' in its OAuth settings, or put "
                "the Consumer Secret in .env as SF_CLIENT_SECRET and run setup again."
            )
        raise SalesforceAuthError(f"login code exchange failed: {detail}.{hint}")
    if "refresh_token" not in payload:
        raise SalesforceAuthError(
            "Salesforce issued no refresh token -- confirm the app's OAuth scopes "
            "include 'Perform requests at any time (refresh_token, offline_access)'."
        )
    return payload


def userinfo(instance_url: str, access_token: str) -> dict[str, Any]:
    """Who did we just log in as? Used by setup to confirm before saving."""
    response = httpx.get(
        f"{instance_url.rstrip('/')}/services/oauth2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise SalesforceAuthError(f"userinfo failed: HTTP {response.status_code}")
    return response.json()
