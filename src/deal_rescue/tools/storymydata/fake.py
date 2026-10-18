"""Offline StoryMyData (Phase 1).

Writes the exact request body it *would* have posted to `.runs/stories/` so the
mapping can be eyeballed (and diffed) without burning the live endpoint's
per-IP quota, then returns a deterministic URL.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from deal_rescue.tools.storymydata.contract import StoryRequest, StoryResult


class FakeStoryMyData:
    def __init__(self, base_url: str, state_dir: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.state_dir = Path(state_dir) / "stories"

    def create_story(self, request: StoryRequest) -> StoryResult:
        body = request.to_api()
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]

        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / f"{digest}.json").write_text(
            json.dumps(body, indent=2), encoding="utf-8"
        )

        return StoryResult(
            ok=True,
            url=f"{self.base_url}/app.html#s=fake-{digest}",
            shape=request.shape,
            template=request.template,
            issues=[],
        )
