"""Live StoryMyData create_story (Phase 2.5).

Fully wired -- the endpoint exists and is public (no auth, per-IP daily cap).
Flip `STORYMYDATA_MODE=live` and point `STORYMYDATA_BASE_URL` at the deployment.
"""

from __future__ import annotations

from typing import Any

import httpx

from deal_rescue.settings import HTTP_TIMEOUT, Settings
from deal_rescue.tools.base import ToolError
from deal_rescue.tools.storymydata.contract import StoryRequest, StoryResult

API_PATH = "/api/story"


class LiveStoryMyData:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.storymydata_base_url.rstrip("/")

    def create_story(self, request: StoryRequest) -> StoryResult:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.storymydata_api_key:
            headers["Authorization"] = f"Bearer {self.settings.storymydata_api_key}"

        try:
            response = httpx.post(
                f"{self.base_url}{API_PATH}",
                json=request.to_api(),
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ToolError(f"StoryMyData request failed: {exc}") from exc

        payload: dict[str, Any]
        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolError(
                f"StoryMyData returned non-JSON (HTTP {response.status_code})"
            ) from exc

        if response.status_code == 429:
            raise ToolError(f"StoryMyData rate limit: {payload.get('error')}")
        if not response.is_success or not payload.get("ok"):
            raise ToolError(
                f"StoryMyData rejected the story (HTTP {response.status_code}): "
                f"{payload.get('error') or payload.get('issues')}"
            )

        return StoryResult(**payload)
