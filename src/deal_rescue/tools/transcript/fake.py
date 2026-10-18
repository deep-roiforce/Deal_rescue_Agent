"""Fixture-backed transcript lookup (Phase 1).

Curated transcripts first (shared with the live adapter), then any hand-placed
cache file, then honest emptiness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deal_rescue.tools.transcript.contract import TranscriptResult
from deal_rescue.tools.transcript.curated import curated_transcript
from deal_rescue.tools.web_research.contract import slugify


class FakeTranscript:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = Path(fixtures_dir)

    def fetch_latest(self, account_name: str, *, deal_id: str | None = None) -> dict[str, Any]:
        curated = curated_transcript(self.fixtures_dir, account_name)
        if curated is not None:
            return curated

        path = self.fixtures_dir / "transcript_cache" / f"{slugify(account_name)}.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return TranscriptResult(**raw).as_state()

        return TranscriptResult(
            found=False, reason=f"no transcript Doc found for {account_name}"
        ).as_state()
