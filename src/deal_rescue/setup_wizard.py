"""First-run setup: `python -m deal_rescue.cli setup`.

Every user is asked two logins and one key:

  [1/3] Salesforce -- browser login (OAuth PKCE)
  [2/3] Google     -- browser login (OAuth PKCE), read-only Drive, for
                      meeting transcripts. Skippable: it is enrichment (D4)
  [3/3] Tavily     -- the key, validated with a real search before saving

Where things land is deliberate: `.env` keeps APP configuration (client IDs,
org URL, API keys -- identical for every user), while each person's refresh
tokens land in their own profile under `.credentials/` (see profiles.py).
That is what makes "login with Google, per user" literally true on one
machine: run setup as someone else and you get a second profile; `--as`
switches between them.

Every step is idempotent -- a login that already exists and still works is
kept -- and secrets never echo beyond their last four characters.
"""

from __future__ import annotations

import secrets as _secrets
import sys
import webbrowser
from pathlib import Path

import httpx

from deal_rescue import gdrive, profiles
from deal_rescue.settings import REPO_ROOT, Settings
from deal_rescue.sfdc import (
    SalesforceAuthError,
    SalesforceClient,
    authorize_url,
    exchange_login_code,
    generate_pkce_pair,
    userinfo,
    wait_for_login_code,
)
from deal_rescue.tools.web_research.live import TAVILY_URL

ENV_PATH = REPO_ROOT / ".env"
EXAMPLE_PATH = REPO_ROOT / ".env.example"

# .env editing lives in envfile.py so the Salesforce transport can persist a
# rotated refresh token without importing the wizard. Re-exported for callers.
from deal_rescue.envfile import update_env  # noqa: E402


def ensure_env() -> None:
    if not ENV_PATH.exists() and EXAMPLE_PATH.exists():
        ENV_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print("  created .env from .env.example")


def current_settings() -> Settings:
    """Fresh .env read, hydrated with the active user's profile."""
    return profiles.apply(Settings())


# --- small console helpers ---------------------------------------------------
def mask(value: str | None) -> str:
    if not value:
        return "not set"
    return f"...{value[-4:]}" if len(value) > 8 else "set"


def header(step: int, total: int, title: str) -> None:
    print(f"\n[{step}/{total}] {title}")
    print("-" * (8 + len(title)))


def ok(message: str) -> None:
    print(f"  ✓ {message}")


def fail(message: str) -> None:
    print(f"  ✗ {message}")


def ask(prompt: str, *, non_interactive: bool) -> str | None:
    if non_interactive:
        return None
    try:
        return input(f"  {prompt}: ").strip() or None
    except EOFError:
        return None


# --- step 1: Salesforce ------------------------------------------------------
def _stored_sf_login(settings: Settings) -> dict | None:
    """Who the stored Salesforce login belongs to, or None if it is broken."""
    if not settings.sf_refresh_token:
        return None
    try:
        client = SalesforceClient(settings)
        client._ensure_token()
        return userinfo(client.instance_url, client._token or "")
    except SalesforceAuthError:
        return None


def _save_sf_profile(settings: Settings, who: dict, tokens: dict) -> str:
    email = (who.get("preferred_username") or who.get("email") or "").lower()
    profiles.save(
        settings,
        email,
        name=who.get("name") or email,
        salesforce={
            "refresh_token": tokens["refresh_token"],
            "instance_url": tokens.get("instance_url") or settings.sf_instance_url,
            "username": email,
        },
    )
    # .env keeps app config; the person's token now lives in their profile.
    update_env(ENV_PATH, {"DEAL_RESCUE_USER": email, "SF_MODE": "live",
                          "SF_REFRESH_TOKEN": ""})
    return email


def setup_salesforce(settings: Settings, *, non_interactive: bool) -> Settings:
    header(1, 3, "Salesforce")

    if not settings.sf_client_id:
        print("  Setup needs your app's Consumer Key (a public identifier, not a secret).")
        print("  Find it in Salesforce Setup -> External Client Apps -> your app ->")
        print("  Settings -> OAuth Settings -> Consumer Key and Secret.")
        entered = ask("Consumer Key", non_interactive=non_interactive)
        if not entered:
            raise SalesforceAuthError("SF_CLIENT_ID is not set -- add it to .env or run interactively")
        update_env(ENV_PATH, {"SF_CLIENT_ID": entered})
        settings = current_settings()
    ok(f"consumer key {mask(settings.sf_client_id)}")

    already = _stored_sf_login(settings)
    if already:
        email = (already.get("preferred_username") or "").lower()
        ok(f"already logged in as {already.get('name')} ({email}) -- keeping it")
        if email and profiles.load(settings, email) is None:
            # Migration: the token predates profiles and lives in .env.
            _save_sf_profile(settings, already,
                             {"refresh_token": settings.sf_refresh_token,
                              "instance_url": settings.sf_instance_url})
            ok(f"moved the login out of .env into its own profile: .credentials/{email}.json")
        update_env(ENV_PATH, {"SF_MODE": "live"})
        return current_settings()

    verifier, challenge = generate_pkce_pair()
    state = _secrets.token_urlsafe(16)
    url = authorize_url(settings, challenge, state)

    print("  A browser window is opening. Log in with your Salesforce account")
    print("  and click Allow. Your password goes to Salesforce, never here.")
    print(f"  If no window opens, paste this into a browser:\n    {url}")
    webbrowser.open(url)

    code = wait_for_login_code(settings, state)
    tokens = exchange_login_code(settings, code, verifier)
    who = userinfo(tokens["instance_url"], tokens["access_token"])
    email = _save_sf_profile(settings, who, tokens)
    ok(f"logged in as {who.get('name')} ({email})")
    ok(f"saved to your profile: .credentials/{email}.json")

    # Prove the *stored* path end to end: fresh settings, profile, SOQL.
    fresh = current_settings()
    rows = SalesforceClient(fresh).query("SELECT Id FROM Organization LIMIT 1")
    ok(f"verified: stored login reaches the org ({len(rows)} row)")
    return fresh


# --- step 2: Google ----------------------------------------------------------
def _stored_google_works(settings: Settings) -> bool:
    if not settings.google_refresh_token:
        return False
    try:
        gdrive.DriveClient(settings).probe()
        return True
    except Exception:  # noqa: BLE001 -- any failure means "log in again"
        return False


def setup_google(settings: Settings, *, non_interactive: bool) -> Settings:
    """Every user is asked to connect Gmail/Google -- it is how the agent reads
    meeting transcripts from Drive. Read-only scope; it cannot send mail. The
    one thing it must never do is brick the agent: transcripts are enrichment,
    so declining leaves everything else working (D4)."""
    header(2, 3, "Google (meeting transcripts)")

    user = settings.deal_rescue_user or ""

    if _stored_google_works(settings):
        ok("already connected to Google Drive -- keeping the stored login")
        if user and not (profiles.load(settings, user) or {}).get("google"):
            profiles.save(settings, user,
                          google={"refresh_token": settings.google_refresh_token})
            update_env(ENV_PATH, {"GOOGLE_REFRESH_TOKEN": ""})
            ok(f"moved the Google login into your profile: .credentials/{user}.json")
        update_env(ENV_PATH, {"TRANSCRIPT_MODE": "live"})
        return current_settings()

    if not (settings.google_client_id and settings.google_client_secret):
        print("  Connecting Google needs a one-time OAuth client (Desktop type):")
        print("    1. console.cloud.google.com -> create/pick a project")
        print("    2. APIs & Services -> Library -> enable 'Google Drive API'")
        print("    3. OAuth consent screen -> External -> add yourself as a test user")
        print("    4. Credentials -> Create credentials -> OAuth client ID -> Desktop app")
        client_id = settings.google_client_id or ask(
            "Google client ID (Enter to skip transcripts for now)",
            non_interactive=non_interactive,
        )
        if not client_id:
            fail("skipped -- transcripts stay off until you re-run setup")
            return settings
        client_secret = settings.google_client_secret or ask(
            "Google client secret", non_interactive=non_interactive
        )
        if not client_secret:
            fail("skipped -- transcripts stay off until you re-run setup")
            return settings
        update_env(ENV_PATH, {"GOOGLE_CLIENT_ID": client_id,
                              "GOOGLE_CLIENT_SECRET": client_secret})
        settings = current_settings()

    verifier, challenge = gdrive.generate_pkce_pair()
    state = _secrets.token_urlsafe(16)
    url = gdrive.authorize_url(settings, challenge, state)

    print("  A browser window is opening. Choose your Google account and allow")
    print("  read-only Drive access. This login cannot send email.")
    print(f"  If no window opens, paste this into a browser:\n    {url}")
    webbrowser.open(url)

    code = gdrive.wait_for_login_code(settings, state, callback_path=gdrive.CALLBACK_PATH)
    tokens = gdrive.exchange_login_code(settings, code, verifier)
    who = gdrive.google_userinfo(tokens["access_token"])
    google_email = who.get("email", "unknown account")
    ok(f"connected as {google_email}")

    if user:
        profiles.save(settings, user,
                      google={"refresh_token": tokens["refresh_token"],
                              "email": google_email})
        update_env(ENV_PATH, {"TRANSCRIPT_MODE": "live", "GOOGLE_REFRESH_TOKEN": ""})
        ok(f"saved to your profile: .credentials/{user}.json")
    else:
        # No Salesforce identity to hang the profile on; .env still works.
        update_env(ENV_PATH, {"GOOGLE_REFRESH_TOKEN": tokens["refresh_token"],
                              "TRANSCRIPT_MODE": "live"})
        ok("saved to .env")

    fresh = current_settings()
    gdrive.DriveClient(fresh).probe()
    ok("verified: stored login reaches Google Drive")
    return fresh


# --- step 3: Tavily ----------------------------------------------------------
def _tavily_key_works(key: str) -> tuple[bool, str]:
    try:
        response = httpx.post(
            TAVILY_URL,
            json={"api_key": key, "query": "salesforce", "max_results": 1,
                  "search_depth": "basic", "topic": "general"},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        return False, f"could not reach Tavily: {exc}"
    if response.status_code in (401, 403):
        return False, "Tavily rejected the key"
    if response.status_code != 200:
        return False, f"Tavily answered HTTP {response.status_code}"
    return True, "key works"


def setup_tavily(settings: Settings, *, non_interactive: bool) -> None:
    header(3, 3, "Tavily (web research)")

    key = settings.search_api_key
    for attempt in range(3):
        if not key:
            print("  Get a free key at https://tavily.com (about a minute).")
            key = ask("Tavily API key", non_interactive=non_interactive)
            if not key:
                raise RuntimeError("SEARCH_API_KEY is not set -- add it to .env or run interactively")

        works, detail = _tavily_key_works(key)
        if works:
            ok(f"key {mask(key)} validated with a live search")
            update_env(ENV_PATH, {"SEARCH_API_KEY": key, "WEB_MODE": "live"})
            ok("saved to .env -- web research is now live")
            return

        fail(detail)
        if non_interactive:
            raise RuntimeError(f"Tavily key invalid: {detail}")
        key = None

    raise RuntimeError("three invalid Tavily keys -- giving up")


# --- entry point ---------------------------------------------------------------
def run_wizard(non_interactive: bool | None = None) -> int:
    if non_interactive is None:
        non_interactive = not sys.stdin.isatty()

    # A wizard that says nothing until it exits is broken: when stdout is a
    # pipe, Python block-buffers and the login URL never appears while the
    # server is still waiting for the login. Flush per line.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    print("Deal Rescue setup")
    print("=================")
    ensure_env()

    try:
        settings = setup_salesforce(current_settings(), non_interactive=non_interactive)
        settings = setup_google(settings, non_interactive=non_interactive)
        setup_tavily(settings, non_interactive=non_interactive)
    except (SalesforceAuthError, gdrive.GoogleAuthError, RuntimeError) as exc:
        fail(str(exc))
        return 1

    final = current_settings()
    print("\nAll set. Try it:")
    print("  python -m deal_rescue.cli shortlist")
    print("  python -m deal_rescue.cli rescue meridian")
    if final.deal_rescue_user:
        print(f"\nActive user: {final.deal_rescue_user}"
              f"  (profiles: {', '.join(profiles.list_profiles(final))})")
        print("Another person on this machine? They just run setup too; switch with --as.")
    print("Optional: add LANGSMITH_API_KEY to .env for full run traces.")
    return 0
