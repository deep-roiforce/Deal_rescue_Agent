"""Single settings module (spec §11).

Every tunable lives here: tool modes, orchestrator knobs, score weights, and
credentials for the live adapters. Nothing else in the codebase reads os.environ.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from functools import lru_cache
from pathlib import Path

import httpx

from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every outbound HTTP call in the codebase uses one of these two budgets, so a
# degraded upstream can stall a run by at most the read window -- never hang it.
# (Plain constants, not env: a timeout you can misconfigure away is not a timeout.)
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
HTTP_TIMEOUT_LONG = httpx.Timeout(60.0, connect=10.0)  # SOQL pagination, Doc export

# tool name -> the Settings field that overrides TOOL_MODE for it
MODE_FIELDS = {
    "salesforce_reads": "sf_mode",
    "salesforce_writeback": "sf_writeback_mode",
    "web_research": "web_mode",
    "transcript": "transcript_mode",
    "agentforce": "agentforce_mode",
    "storymydata": "storymydata_mode",
}


class ToolMode(str, Enum):
    """How a tool reaches its backing service."""

    FAKE = "fake"  # fixture-backed; no network. Phase 1 default.
    LIVE = "live"  # real MCP / HTTP adapter. Phase 2.


class ScoreWeights(BaseSettings):
    """Deterministic rubric constants (spec §7).

    D12: configurable by design, no config UI in the demo.
    """

    model_config = SettingsConfigDict(env_prefix="SCORE_", env_file=".env", extra="ignore")

    start: int = 100
    days_silent_cap: int = 45
    days_silent_weight: float = 1.0
    close_date_push_weight: float = 8.0
    stage_regression_weight: float = 15.0
    activity_slope_weight: float = 10.0
    activity_slope_window_days: int = 30
    llm_adjustment_bound: int = 15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- global ------------------------------------------------------------
    tool_mode: ToolMode = ToolMode.FAKE
    as_of: date | None = None  # deterministic "today" for demo/tests
    state_dir: Path = REPO_ROOT / ".runs"
    fixtures_dir: Path = REPO_ROOT / "fixtures"
    # Per-user credential profiles (see profiles.py). .env is app config;
    # who-is-logged-in lives one file per person under this directory.
    credentials_dir: Path = REPO_ROOT / ".credentials"
    deal_rescue_user: str | None = None  # default profile; --as overrides

    # --- orchestrator knobs ------------------------------------------------
    stall_days: int = 14
    shortlist_n: int = 5
    # Which lane the shortlist ranks by (D12, configurable by design):
    #   risk     -> amount x (100 - health). The rescue queue. Default.
    #   exposure -> amount x stall_days. Pipeline hygiene; spec's ranking v1.
    shortlist_ranking: str = "risk"
    # D1: the shortlist is a daily batch. While the API server runs it
    # refreshes itself on this interval; 0 disables (manual refresh only).
    shortlist_refresh_hours: float = 24.0
    max_synth_retries: int = 2

    # --- tool: salesforce_reads -------------------------------------------
    sf_mode: ToolMode | None = None
    sf_mcp_url: str | None = None
    sf_instance_url: str | None = None
    sf_client_id: str | None = None
    sf_username: str | None = None
    sf_private_key_path: Path | None = None
    sf_login_url: str = "https://login.salesforce.com"  # test.salesforce.com for sandboxes
    sf_api_version: str = "62.0"
    # Extra SOQL predicate for the shortlist, e.g. "Account.BillingState = 'IN'".
    # Demo orgs are full of unrelated pipeline.
    sf_opportunity_filter: str | None = None
    # The org's stage pipeline, in order, comma separated. Leave unset for the
    # fixture vocabulary. Live orgs should supply their own picklist order --
    # a stage this rubric cannot rank is a regression it cannot see.
    sf_stage_order: str | None = None
    # Interactive login (PKCE) -- what `cli setup` stores. When a refresh token
    # is present it is the auth path; the JWT certificate flow is the headless
    # alternative and is used only when this is unset.
    sf_refresh_token: str | None = None
    sf_client_secret: str | None = None  # only if the app demands one at token exchange
    sf_callback_port: int = 1717  # must match the app's registered callback URL

    # --- tool: salesforce_writeback ---------------------------------------
    sf_writeback_mode: ToolMode | None = None

    # --- tool: web_research ------------------------------------------------
    web_mode: ToolMode | None = None
    search_provider: str = "tavily"
    search_api_key: str | None = None

    # --- tool: transcript --------------------------------------------------
    transcript_mode: ToolMode | None = None
    google_credentials_path: Path | None = None  # service-account alternative, unused by setup
    google_drive_folder_id: str | None = None
    # User OAuth (the `cli setup` path): a Desktop-type OAuth client from the
    # Google Cloud console, plus the refresh token the login stores. Scope is
    # read-only Drive -- this login cannot send mail or write anything.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_refresh_token: str | None = None

    # --- tool: agentforce (the synthesis step) ------------------------------
    agentforce_mode: ToolMode | None = None
    # Which backend supplies judgment when the mode is live. The prompt, the
    # merge fields and the validation gate are identical either way -- the
    # provider is just the transport (amended D5, see docs/decisions.md).
    #   anthropic  -> Claude via the Anthropic API. Default.
    #   agentforce -> the Agentforce Agent API behind an MCP wrapper (Phase 2.4)
    synthesis_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    synthesis_model: str = "claude-opus-5-5"
    agentforce_mcp_url: str | None = None
    agentforce_agent_id: str | None = None
    agentforce_api_url: str | None = None
    agentforce_fake_fault: str | None = None  # fake-only gate exercise

    # --- tool: storymydata -------------------------------------------------
    storymydata_mode: ToolMode | None = None
    storymydata_base_url: str = "https://storymydata.local"
    storymydata_api_key: str | None = None

    # --- rubric ------------------------------------------------------------
    score: ScoreWeights = Field(default_factory=ScoreWeights)

    # -----------------------------------------------------------------------
    @model_validator(mode="before")
    @classmethod
    def _blank_means_unset(cls, data: Any) -> Any:
        """A blank line in .env means "not set", not "the empty string".

        `.env.example` ships every optional key with an empty value so they are
        discoverable. Without this, copying it to `.env` -- the first thing any
        new user does -- fails validation on every enum field.
        """
        if isinstance(data, dict):
            return {
                key: value
                for key, value in data.items()
                if not (isinstance(value, str) and not value.strip())
            }
        return data

    def mode_for(self, tool_name: str) -> ToolMode:
        """Per-tool mode, falling back to the global TOOL_MODE."""
        field = MODE_FIELDS.get(tool_name)
        if field is None:
            raise KeyError(f"unknown tool: {tool_name}")
        return getattr(self, field) or self.tool_mode

    def stage_order(self) -> list[str] | None:
        """Org stage pipeline, or None to use the built-in default."""
        if not self.sf_stage_order:
            return None
        return [part.strip() for part in self.sf_stage_order.split(",") if part.strip()]

    def today(self) -> date:
        return self.as_of or date.today()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests call this after mutating the environment."""
    get_settings.cache_clear()
