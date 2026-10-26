"""Website-style sign-in for the dashboard.

The buttons everyone knows: click "Sign in with Google", get Google's own
consent screen, land back on the dashboard connected. Same for Salesforce.
Both flows end in the same per-user profile store the CLI wizard writes, so
the two entry points are interchangeable.

Flow mechanics: `start()` parks a PKCE verifier server-side under a random
`state` and hands back the provider's authorize URL; the provider redirects to
`/auth/<provider>/callback?code&state`; `finish()` redeems the state (single
use, ten-minute expiry), exchanges the code with the SAME redirect_uri, and
saves the tokens into the right profile. An unknown or reused state dies here
-- a forged or replayed callback never reaches a token exchange.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from deal_rescue import gdrive, profiles, sfdc
from deal_rescue.envfile import ENV_PATH, update_env
from deal_rescue.settings import Settings

# state -> {provider, verifier, redirect_uri, created}
PENDING: dict[str, dict[str, Any]] = {}
STATE_TTL_SECONDS = 600


class WebAuthError(RuntimeError):
    pass


def _begin(provider: str, verifier: str, redirect_uri: str) -> str:
    now = time.time()
    for state in [s for s, p in PENDING.items() if now - p["created"] > STATE_TTL_SECONDS]:
        del PENDING[state]
    state = secrets.token_urlsafe(24)
    PENDING[state] = {
        "provider": provider, "verifier": verifier,
        "redirect_uri": redirect_uri, "created": now,
    }
    return state


def _redeem(state: str, provider: str) -> dict[str, Any]:
    pending = PENDING.pop(state, None)  # single use, even on failure
    if pending is None or pending["provider"] != provider:
        raise WebAuthError(
            "this sign-in link was already used or has expired -- click the button again"
        )
    if time.time() - pending["created"] > STATE_TTL_SECONDS:
        raise WebAuthError("this sign-in took longer than ten minutes -- click the button again")
    return pending


def callback_url(base_url: str, provider: str) -> str:
    return f"{base_url.rstrip('/')}/auth/{provider}/callback"


# --- Salesforce ----------------------------------------------------------------
def salesforce_start(settings: Settings, base_url: str) -> str:
    verifier, challenge = sfdc.generate_pkce_pair()
    redirect = callback_url(base_url, "salesforce")
    state = _begin("salesforce", verifier, redirect)
    return sfdc.authorize_url(settings, challenge, state, redirect_override=redirect)


def salesforce_finish(settings: Settings, code: str, state: str) -> str:
    pending = _redeem(state, "salesforce")
    tokens = sfdc.exchange_login_code(
        settings, code, pending["verifier"], redirect_override=pending["redirect_uri"]
    )
    who = sfdc.userinfo(tokens["instance_url"], tokens["access_token"])
    email = (who.get("preferred_username") or who.get("email") or "").lower()
    if not email:
        raise WebAuthError("Salesforce reported no username for this login")

    profiles.save(
        settings, email,
        name=who.get("name") or email,
        salesforce={
            "refresh_token": tokens["refresh_token"],
            "instance_url": tokens.get("instance_url"),
            "username": email,
        },
    )
    update_env(ENV_PATH, {"DEAL_RESCUE_USER": email, "SF_MODE": "live",
                          "SF_REFRESH_TOKEN": ""})
    return email


# --- Google ----------------------------------------------------------------------
def google_start(settings: Settings, base_url: str) -> str:
    if not settings.deal_rescue_user:
        raise WebAuthError("connect Salesforce first -- the Google login attaches to your user")
    verifier, challenge = gdrive.generate_pkce_pair()
    redirect = callback_url(base_url, "google")
    state = _begin("google", verifier, redirect)
    return gdrive.authorize_url(settings, challenge, state, redirect_override=redirect)


def google_finish(settings: Settings, code: str, state: str) -> str:
    user = settings.deal_rescue_user
    if not user:
        raise WebAuthError("connect Salesforce first -- the Google login attaches to your user")

    pending = _redeem(state, "google")
    tokens = gdrive.exchange_login_code(
        settings, code, pending["verifier"], redirect_override=pending["redirect_uri"]
    )
    who = gdrive.google_userinfo(tokens["access_token"])
    google_email = who.get("email", "unknown account")

    profiles.save(settings, user,
                  google={"refresh_token": tokens["refresh_token"], "email": google_email})
    update_env(ENV_PATH, {"TRANSCRIPT_MODE": "live", "GOOGLE_REFRESH_TOKEN": ""})
    return google_email


# --- status for the header -----------------------------------------------------
def status(settings: Settings) -> dict[str, Any]:
    user = settings.deal_rescue_user
    record = profiles.load(settings, user) if user else None
    salesforce = record.get("salesforce") if record else None
    google = record.get("google") if record else None
    sa_email = gdrive.service_account_email(settings)
    return {
        "user": user,
        "name": (record or {}).get("name"),
        "salesforce_connected": bool((salesforce or {}).get("refresh_token")
                                     or settings.sf_refresh_token),
        "google_connected": bool((google or {}).get("refresh_token")
                                 or settings.google_refresh_token or sa_email),
        "google_account": (google or {}).get("email") or sa_email,
        "salesforce_configured": bool(settings.sf_client_id),
        "google_configured": bool(settings.google_client_id and settings.google_client_secret),
    }
