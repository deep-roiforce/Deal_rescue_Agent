"""The setup page's backend: get-started configuration over the dashboard.

The browser twin of `setup_wizard.py`. A new user opens /setup, pastes the
four credentials (Salesforce consumer key, Google OAuth client, Tavily key,
Anthropic key), clicks the two sign-in buttons, and the agent is live --
no .env editing, no terminal.

Ground rules:
* Values are WRITE-ONLY through this surface. Status reports `set` plus the
  last four characters -- a secret that goes in never comes back out.
* Only whitelisted keys reach .env (`FIELDS`); everything else is rejected.
* Saving a Tavily/Anthropic key also flips that tool's mode to live, matching
  what the CLI wizard does.
"""

from __future__ import annotations

from typing import Any

from deal_rescue import envfile
from deal_rescue.settings import Settings

# form field -> (ENV name, is_secret)
FIELDS: dict[str, tuple[str, bool]] = {
    "sf_client_id": ("SF_CLIENT_ID", True),
    "google_client_id": ("GOOGLE_CLIENT_ID", True),
    "google_client_secret": ("GOOGLE_CLIENT_SECRET", True),
    "search_api_key": ("SEARCH_API_KEY", True),
    "anthropic_api_key": ("ANTHROPIC_API_KEY", True),
    "synthesis_model": ("SYNTHESIS_MODEL", False),
    "google_drive_folder_id": ("GOOGLE_DRIVE_FOLDER_ID", False),
}

# saving this field proves intent to go live with that tool
MODE_FLIPS = {
    "search_api_key": ("WEB_MODE", "live"),
    "anthropic_api_key": ("AGENTFORCE_MODE", "live"),
}

MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")


def _hint(value: str | None) -> str | None:
    """Enough to recognize a key, never enough to use one."""
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 8 else "set"


def status(settings: Settings) -> dict[str, Any]:
    from deal_rescue import webauth

    return {
        "fields": {
            "sf_client_id": {"set": bool(settings.sf_client_id),
                             "hint": _hint(settings.sf_client_id)},
            "google_client_id": {"set": bool(settings.google_client_id),
                                 "hint": _hint(settings.google_client_id)},
            "google_client_secret": {"set": bool(settings.google_client_secret)},
            "search_api_key": {"set": bool(settings.search_api_key),
                               "hint": _hint(settings.search_api_key)},
            "anthropic_api_key": {"set": bool(settings.anthropic_api_key),
                                  "hint": _hint(settings.anthropic_api_key)},
            "synthesis_model": {"value": settings.synthesis_model, "options": list(MODELS)},
            "google_drive_folder_id": {"value": settings.google_drive_folder_id or ""},
        },
        "modes": {
            name: settings.mode_for(name).value
            for name in ("salesforce_reads", "web_research", "transcript", "agentforce")
        },
        "auth": webauth.status(settings),
    }


def apply_config(values: dict[str, Any]) -> dict[str, Any]:
    """Validate, whitelist, write to .env. Returns what was saved (names only)."""
    unknown = sorted(set(values) - set(FIELDS))
    if unknown:
        raise ValueError(f"unknown setup field(s): {', '.join(unknown)}")

    env_updates: dict[str, str] = {}
    saved: list[str] = []
    for field, raw in values.items():
        value = str(raw or "").strip()
        if not value:
            continue  # blank input means "leave as is", never "erase"
        if field == "synthesis_model" and value not in MODELS:
            raise ValueError(f"synthesis_model must be one of {', '.join(MODELS)}")
        env_name, _secret = FIELDS[field]
        env_updates[env_name] = value
        saved.append(field)
        if field in MODE_FLIPS:
            mode_env, mode_value = MODE_FLIPS[field]
            env_updates[mode_env] = mode_value

    if env_updates:
        envfile.update_env(envfile.ENV_PATH, env_updates)
    return {"saved": saved}


def test_service(service: str, settings: Settings) -> dict[str, Any]:
    """A cheap end-to-end probe per key, so 'saved' can become 'works'."""
    if service == "tavily":
        from deal_rescue.setup_wizard import _tavily_key_works

        if not settings.search_api_key:
            return {"ok": False, "detail": "no key saved yet"}
        ok, detail = _tavily_key_works(settings.search_api_key)
        return {"ok": ok, "detail": detail}

    if service == "anthropic":
        if not settings.anthropic_api_key:
            return {"ok": False, "detail": "no key saved yet"}
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            models = [m.id for m in client.models.list(limit=50)]
        except ImportError:
            return {"ok": False, "detail": 'anthropic SDK missing -- pip install -e ".[synthesis]"'}
        except Exception as exc:  # noqa: BLE001 -- the page shows the reason
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}
        if settings.synthesis_model not in models:
            return {"ok": True,
                    "detail": f"key works, but {settings.synthesis_model} not in the "
                              "account's model list"}
        return {"ok": True, "detail": f"key works; {settings.synthesis_model} available"}

    return {"ok": False, "detail": f"unknown service {service!r}"}
