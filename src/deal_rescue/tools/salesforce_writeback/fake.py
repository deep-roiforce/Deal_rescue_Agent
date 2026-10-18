"""Offline write-back (Phase 1).

Persists the payload to `.runs/writebacks/<deal_id>.json` so the demo can show
"here is exactly what would land in the org" before the org build exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from deal_rescue.tools.salesforce_writeback.contract import WritebackPayload, WritebackResult


class FakeSalesforceWriteback:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir) / "writebacks"

    def create_rescue_writeback(self, payload: WritebackPayload) -> WritebackResult:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / f"{payload.deal_id}.json").write_text(
            json.dumps(payload.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        suffix = payload.deal_id[-6:]
        return WritebackResult(
            opportunity_updated=True,
            rescue_result_id=f"a0R{suffix}FAKE01",
            draft_task_id=f"00T{suffix}FAKE01" if payload.email_draft else None,
            audit_task_ids=[
                f"00T{suffix}AUD{index:03d}" for index in range(len(payload.audit_findings))
            ],
        )
