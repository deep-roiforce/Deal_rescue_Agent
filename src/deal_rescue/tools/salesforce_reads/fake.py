"""Fixture-backed org reads (Phase 1).

Meridian has a full hand-authored fixture; the filler shortlist deals get a
minimal synthetic OrgData so the graph still runs end-to-end for any of them.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from deal_rescue.tools.base import ToolError
from deal_rescue.tools.salesforce_reads.contract import (
    Account,
    Activity,
    ContactRole,
    Opportunity,
    OrgData,
    StageChange,
)

MERIDIAN_DEAL_ID = "006MER0000000001"


@lru_cache
def _load(path: str) -> dict | list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class FakeSalesforceReads:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = Path(fixtures_dir)

    # --- raw fixture access ------------------------------------------------
    def _meridian(self) -> dict:
        return dict(_load(str(self.fixtures_dir / "meridian" / "org_data.json")))  # type: ignore[arg-type]

    def _stalled(self) -> list[dict]:
        return list(_load(str(self.fixtures_dir / "shortlist" / "stalled_opportunities.json")))  # type: ignore[arg-type]

    def _opp_record(self, deal_id: str) -> dict:
        for opp in self._stalled():
            if opp["id"] == deal_id:
                return opp
        raise ToolError(f"unknown deal_id in fixtures: {deal_id}")

    # --- contract ----------------------------------------------------------
    def get_opportunity(self, deal_id: str) -> Opportunity:
        if deal_id == MERIDIAN_DEAL_ID:
            return Opportunity(**self._meridian()["opportunity"])
        return Opportunity(**self._opp_record(deal_id))

    def get_opportunity_history(self, deal_id: str) -> list[StageChange]:
        if deal_id == MERIDIAN_DEAL_ID:
            return [StageChange(**c) for c in self._meridian()["stage_history"]]
        opp = self._opp_record(deal_id)
        return [
            StageChange(
                date=opp["created_date"],
                field="StageName",
                old_value=None,
                new_value="Discovery",
                amount=opp["amount"],
            ),
            StageChange(
                date=opp["last_activity_date"],
                field="StageName",
                old_value="Discovery",
                new_value=opp["stage"],
                amount=opp["amount"],
            ),
        ]

    def get_contact_roles(self, deal_id: str) -> list[ContactRole]:
        if deal_id == MERIDIAN_DEAL_ID:
            return [ContactRole(**c) for c in self._meridian()["contact_roles"]]
        opp = self._opp_record(deal_id)
        return [
            ContactRole(
                contact_id=f"003{opp['id'][3:]}",
                name=f"{opp['account_name']} Buyer",
                title="Operations Lead",
                role="Decision Maker",
                email="buyer@example.com",
                is_primary=True,
            )
        ]

    def get_activity_timeline(self, deal_id: str, months: int = 6) -> list[Activity]:
        if deal_id == MERIDIAN_DEAL_ID:
            cutoff = date.fromisoformat(
                self._meridian()["opportunity"]["last_activity_date"]
            ) - timedelta(days=months * 31)
            return [
                Activity(**a)
                for a in self._meridian()["activities"]
                if date.fromisoformat(a["date"]) >= cutoff
            ]
        opp = self._opp_record(deal_id)
        return [
            Activity(
                date=opp["last_activity_date"],
                type="Email",
                subject="Follow-up",
                direction="outbound",
                has_reply=False,
            )
        ]

    def list_stalled_opportunities(self, stall_days: int, as_of: date) -> list[Opportunity]:
        out: list[Opportunity] = []
        for raw in self._stalled():
            opp = Opportunity(**raw)
            if opp.is_closed or opp.last_activity_date is None:
                continue
            if (as_of - opp.last_activity_date).days > stall_days:
                out.append(opp)
        return out

    def fetch_org_data(self, deal_id: str) -> OrgData:
        if deal_id == MERIDIAN_DEAL_ID:
            raw = self._meridian()
            return OrgData(
                account=Account(**raw["account"]),
                opportunity=Opportunity(**raw["opportunity"]),
                stage_history=[StageChange(**c) for c in raw["stage_history"]],
                contact_roles=[ContactRole(**c) for c in raw["contact_roles"]],
                activities=[Activity(**a) for a in raw["activities"]],
            )
        opp = self.get_opportunity(deal_id)
        return OrgData(
            account=Account(id=opp.account_id, name=opp.account_name),
            opportunity=opp,
            stage_history=self.get_opportunity_history(deal_id),
            contact_roles=self.get_contact_roles(deal_id),
            activities=self.get_activity_timeline(deal_id),
        )
