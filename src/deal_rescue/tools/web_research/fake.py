"""Cache/fixture-backed web research (Phase 1).

Curated findings first (shared with the live adapter), then any hand-placed
cache file, then honest emptiness -- which is what routes the filler deals onto
the thin-evidence path (D11).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deal_rescue.tools.base import degraded
from deal_rescue.tools.web_research.contract import WebFindings, slugify
from deal_rescue.tools.web_research.curated import curated_findings


class FakeWebResearch:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = Path(fixtures_dir)

    def search(self, account_name: str, *, queries: list[str] | None = None) -> dict[str, Any]:
        curated = curated_findings(self.fixtures_dir, account_name)
        if curated is not None:
            return curated

        cached = self.fixtures_dir / "web_cache" / f"{slugify(account_name)}.json"
        if cached.exists():
            return WebFindings(**json.loads(cached.read_text(encoding="utf-8"))).as_state()

        return degraded(f"no cached web results for {account_name}")
