"""Per-user credential profiles.

`.env` answers "how is this app configured" -- client IDs, org URL, API keys
that are the same for everyone. A profile answers "who is logged in": one JSON
file per person under `.credentials/`, keyed by the email their Salesforce
login reports, holding their refresh tokens. Two people (or one person with two
orgs) coexist on one machine; `--as someone@example.com` picks between them.

Nothing downstream knows profiles exist. `apply()` hydrates a Settings object
with the chosen profile's tokens, and every transport keeps reading plain
Settings fields. Swapping this store for a database row is a one-module change,
which is the point.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deal_rescue.settings import Settings


def profiles_dir(settings: Settings) -> Path:
    return Path(settings.credentials_dir)


def profile_path(settings: Settings, email: str) -> Path:
    return profiles_dir(settings) / f"{email.strip().lower()}.json"


def load(settings: Settings, email: str) -> dict[str, Any] | None:
    path = profile_path(settings, email)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles(settings: Settings) -> list[str]:
    folder = profiles_dir(settings)
    if not folder.exists():
        return []
    return sorted(path.stem for path in folder.glob("*.json"))


def save(settings: Settings, email: str, **sections: dict[str, Any] | str) -> Path:
    """Merge the given sections into the profile, creating it if needed."""
    path = profile_path(settings, email)
    path.parent.mkdir(parents=True, exist_ok=True)

    profile: dict[str, Any] = load(settings, email) or {"email": email.strip().lower()}
    for key, value in sections.items():
        if isinstance(value, dict):
            merged = dict(profile.get(key) or {})
            merged.update(value)
            profile[key] = merged
        else:
            profile[key] = value
    profile["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return path


def apply(settings: Settings, email: str | None = None) -> Settings:
    """Settings hydrated with the chosen user's credentials.

    Explicit `email` (the --as flag) beats DEAL_RESCUE_USER; no profile on disk
    means the settings pass through untouched, so a .env-only or JWT-only
    configuration keeps working exactly as before.
    """
    chosen = (email or settings.deal_rescue_user or "").strip().lower()
    if not chosen:
        return settings
    profile = load(settings, chosen)
    if profile is None:
        if email:  # explicitly asked for someone who never logged in
            raise FileNotFoundError(
                f"no stored login for {chosen!r} -- run `python -m deal_rescue.cli setup` "
                f"as that user. Known users: {', '.join(list_profiles(settings)) or 'none'}"
            )
        return settings

    updates: dict[str, Any] = {"deal_rescue_user": chosen}
    salesforce = profile.get("salesforce") or {}
    if salesforce.get("refresh_token"):
        updates["sf_refresh_token"] = salesforce["refresh_token"]
    if salesforce.get("instance_url"):
        updates["sf_instance_url"] = salesforce["instance_url"]
    if salesforce.get("username"):
        updates["sf_username"] = salesforce["username"]
    google = profile.get("google") or {}
    if google.get("refresh_token"):
        updates["google_refresh_token"] = google["refresh_token"]

    return settings.model_copy(update=updates)


def replace_sf_refresh_token(settings: Settings, old: str, new: str) -> bool:
    """Persist a rotated Salesforce refresh token into whichever profile holds
    the burned one. Same guard as the .env variant: only a file storing exactly
    the old token is ever rewritten."""
    if not old:
        return False
    for email in list_profiles(settings):
        profile = load(settings, email) or {}
        salesforce = profile.get("salesforce") or {}
        if salesforce.get("refresh_token") == old:
            save(settings, email, salesforce={"refresh_token": new})
            return True
    return False
