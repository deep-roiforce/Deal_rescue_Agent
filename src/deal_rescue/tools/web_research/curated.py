"""Curated (pre-seeded) web findings.

The demo account is fictional, so a live search for it returns real articles
about the wrong companies -- discovered in practice when Meridian Fabrication
came back grounded on a footwear brand and a kiosk vendor. Curated findings are
the spec's answer (4.2 N4): hand-authored results for the demo accounts, the
live pipe for everything real.

Checked by BOTH adapters. The fake never fetches anyway; the live adapter
consults this first and only searches on a miss, which is what keeps the demo
deterministic while the pipe stays real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deal_rescue.tools.web_research.contract import WebFindings, slugify

MERIDIAN_SLUG = "meridian-fabrication"


def curated_findings(fixtures_dir: Path, account_name: str) -> dict[str, Any] | None:
    """Hand-authored findings for this account, or None to search live."""
    slug = slugify(account_name)

    candidates = [fixtures_dir / "curated_web" / f"{slug}.json"]
    if slug == MERIDIAN_SLUG:
        candidates.append(fixtures_dir / "meridian" / "web_findings.json")

    for path in candidates:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return WebFindings(**raw).as_state()
    return None
