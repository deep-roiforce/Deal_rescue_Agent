"""Editing .env in place.

Used by the setup wizard (writing what the user just configured) and by the
Salesforce transport (persisting a rotated refresh token). Lives in its own
module so the transport does not have to import the wizard.
"""

from __future__ import annotations

from pathlib import Path

from deal_rescue.settings import REPO_ROOT

ENV_PATH = REPO_ROOT / ".env"


def update_env(path: Path, values: dict[str, str]) -> None:
    """Set keys in a .env file, replacing existing lines and appending new
    ones, while leaving every other line -- comments included -- untouched."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)

    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in remaining:
            lines[index] = f"{key}={remaining.pop(key)}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# --- added by `cli setup` ---")
        lines.extend(f"{key}={value}" for key, value in remaining.items())

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def replace_refresh_token(old: str, new: str) -> bool:
    """Persist a rotated Salesforce refresh token.

    Deliberately narrow: rewrites .env only when it currently stores exactly
    the token that was just rotated away from, so a test or an env-var-only
    deployment can never cause a surprise write to the repo's .env.
    """
    if not ENV_PATH.exists():
        return False
    if f"SF_REFRESH_TOKEN={old}" not in ENV_PATH.read_text(encoding="utf-8"):
        return False
    update_env(ENV_PATH, {"SF_REFRESH_TOKEN": new})
    return True
