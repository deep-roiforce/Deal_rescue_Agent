"""Curated (pre-seeded) transcripts, mirroring web_research/curated.py.

The fake adapter serves these first -- fixtures are its whole job. The live
adapter is Drive-FIRST (the demo meetings are staged as real Docs in the
configured folder) and reaches for a curated transcript only when Drive has no
Doc or cannot be reached, so the demo survives a missing Google login.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deal_rescue.tools.transcript.contract import TranscriptResult
from deal_rescue.tools.web_research.contract import slugify

MERIDIAN_SLUG = "meridian-fabrication"


def curated_transcript(fixtures_dir: Path, account_name: str) -> dict[str, Any] | None:
    """Hand-authored transcript for this account, or None to look in Drive."""
    slug = slugify(account_name)

    candidates = [fixtures_dir / "curated_transcripts" / f"{slug}.json"]
    if slug == MERIDIAN_SLUG:
        candidates.append(fixtures_dir / "meridian" / "transcript.json")

    for path in candidates:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return TranscriptResult(**raw).as_state()
    return None
