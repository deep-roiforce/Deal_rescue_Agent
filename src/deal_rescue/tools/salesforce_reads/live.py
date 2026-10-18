"""Live org reads over SOQL (Phase 2.1).

Transport is `deal_rescue.sfdc.SalesforceClient` (JWT bearer + SOQL). The MCP
wrapper comes next and will sit on top of this, not replace it -- debugging
"is the SOQL wrong or is the MCP transport wrong" at the same time is miserable.

Two things here are not obvious and cost real time to discover:

1. **OpportunityHistory stores snapshots, not before/after pairs.** Each row is
   the state *after* a change. The `StageChange` contract wants deltas, so
   `history_to_changes()` diffs consecutive rows. That function is pure and
   unit-tested against the shapes the real org returns.

2. **Stage vocabulary belongs to the org.** This org uses the standard picklist
   (Proposal/Price Quote, Negotiation/Review), not the fixtures' shorthand. The
   adapter does not translate: it passes the org's own names through, and the
   org's Apex rubric -- which reads stage order from the picklist -- is the
   authority on what counts as a regression.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from deal_rescue.sfdc import SalesforceClient, flatten, soql_id
from deal_rescue.settings import Settings
from deal_rescue.tools.base import ToolError
from deal_rescue.tools.salesforce_reads.contract import (
    Account,
    Activity,
    ContactRole,
    Opportunity,
    OrgData,
    StageChange,
)

OPPORTUNITY_FIELDS = """
    Id, Name, AccountId, Account.Name, Amount, StageName, CloseDate,
    CreatedDate, LastActivityDate, IsClosed, Owner.Name,
    Rescue_Base_Score__c, Rescue_Base_Signals__c
"""


def as_date(value: Any) -> dt.date | None:
    """SOQL dates arrive as '2026-09-30'; datetimes as ISO with an offset."""
    if not value:
        return None
    if isinstance(value, dt.date):
        return value
    text = str(value)[:10]
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def history_to_changes(rows: list[dict[str, Any]], amount_fallback: float | None) -> list[StageChange]:
    """OpportunityHistory snapshots -> StageChange deltas.

    Rows must be ordered by CreatedDate ascending. The first row is the
    creation snapshot and becomes a StageName change from nothing.
    """
    changes: list[StageChange] = []
    previous: dict[str, Any] | None = None

    for row in rows:
        row_date = as_date(row.get("CreatedDate"))
        amount = row.get("Amount") if row.get("Amount") is not None else amount_fallback

        if previous is None:
            changes.append(StageChange(
                date=row_date, field="StageName", old_value=None,
                new_value=row.get("StageName"), amount=amount,
            ))
            previous = row
            continue

        if row.get("StageName") != previous.get("StageName"):
            changes.append(StageChange(
                date=row_date, field="StageName",
                old_value=previous.get("StageName"), new_value=row.get("StageName"),
                amount=amount,
            ))

        if row.get("CloseDate") != previous.get("CloseDate"):
            changes.append(StageChange(
                date=row_date, field="CloseDate",
                old_value=str(previous.get("CloseDate") or "") or None,
                new_value=str(row.get("CloseDate") or "") or None,
                amount=amount,
            ))

        if row.get("Amount") != previous.get("Amount"):
            changes.append(StageChange(
                date=row_date, field="Amount",
                old_value=str(previous.get("Amount") or "") or None,
                new_value=str(row.get("Amount") or "") or None,
                amount=amount,
            ))

        previous = row

    return changes


def _opportunity(row: dict[str, Any]) -> Opportunity:
    flat = flatten(row)
    return Opportunity(
        id=flat["Id"],
        name=flat["Name"],
        account_id=flat.get("AccountId") or "",
        account_name=flat.get("Account.Name") or "",
        amount=flat.get("Amount"),
        stage=flat.get("StageName") or "",
        close_date=as_date(flat.get("CloseDate")),
        created_date=as_date(flat.get("CreatedDate")) or dt.date.today(),
        last_activity_date=as_date(flat.get("LastActivityDate")),
        is_closed=bool(flat.get("IsClosed")),
        owner_name=flat.get("Owner.Name"),
    )


class LiveSalesforceReads:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = SalesforceClient(settings)

    # --- contract ----------------------------------------------------------
    def get_opportunity(self, deal_id: str) -> Opportunity:
        rows = self.client.query(
            f"SELECT {OPPORTUNITY_FIELDS} FROM Opportunity WHERE Id = '{deal_id}'"
        )
        if not rows:
            # The floor gave way: without org data the run is over (D4).
            raise ToolError(f"opportunity {deal_id} not found or not visible")
        return _opportunity(rows[0])

    def get_opportunity_history(self, deal_id: str) -> list[StageChange]:
        rows = self.client.query(
            "SELECT StageName, Amount, CloseDate, CreatedDate FROM OpportunityHistory "
            f"WHERE OpportunityId = '{deal_id}' ORDER BY CreatedDate ASC"
        )
        opportunity_amount = None
        if rows:
            opportunity_amount = rows[-1].get("Amount")
        return history_to_changes([flatten(r) for r in rows], opportunity_amount)

    def get_contact_roles(self, deal_id: str) -> list[ContactRole]:
        rows = self.client.query(
            "SELECT ContactId, Contact.Name, Contact.Title, Contact.Email, Role, IsPrimary "
            f"FROM OpportunityContactRole WHERE OpportunityId = '{deal_id}'"
        )
        roles: list[ContactRole] = []
        for row in rows:
            flat = flatten(row)
            roles.append(ContactRole(
                contact_id=flat.get("ContactId") or "",
                name=flat.get("Contact.Name") or "",
                title=flat.get("Contact.Title"),
                role=flat.get("Role"),
                email=flat.get("Contact.Email"),
                is_primary=bool(flat.get("IsPrimary")),
                active=True,  # the org has no "departed" flag; that is a web signal
            ))
        return roles

    def get_activity_timeline(self, deal_id: str, months: int = 6) -> list[Activity]:
        cutoff = self.settings.today() - dt.timedelta(days=months * 31)
        activities: list[Activity] = []

        for row in self.client.query(
            "SELECT Subject, ActivityDate, Status, TaskSubtype FROM Task "
            f"WHERE WhatId = '{deal_id}' AND ActivityDate >= {cutoff.isoformat()} "
            "ORDER BY ActivityDate ASC"
        ):
            when = as_date(row.get("ActivityDate"))
            if when is None:
                continue
            subtype = row.get("TaskSubtype") or "Task"
            activities.append(Activity(
                date=when,
                type=subtype,
                subject=row.get("Subject") or "",
                direction="outbound",
            ))

        for row in self.client.query(
            "SELECT Subject, ActivityDate FROM Event "
            f"WHERE WhatId = '{deal_id}' AND ActivityDate >= {cutoff.isoformat()} "
            "ORDER BY ActivityDate ASC"
        ):
            when = as_date(row.get("ActivityDate"))
            if when is None:
                continue
            # Events are meetings. The gate checks `meeting` milestones against
            # these dates, so the distinction is load-bearing.
            activities.append(Activity(
                date=when, type="Event",
                subject=row.get("Subject") or "", direction="meeting",
            ))

        return sorted(activities, key=lambda item: item.date)

    def list_stalled_opportunities(self, stall_days: int, as_of: dt.date) -> list[Opportunity]:
        cutoff = (as_of - dt.timedelta(days=stall_days)).isoformat()
        where = [
            "IsClosed = false",
            f"(LastActivityDate < {cutoff} OR LastActivityDate = null)",
        ]
        # Demo orgs are full of unrelated pipeline. Without this the shortlist
        # ranks deals nobody asked about.
        if self.settings.sf_opportunity_filter:
            where.append(f"({self.settings.sf_opportunity_filter})")

        rows = self.client.query(
            f"SELECT {OPPORTUNITY_FIELDS} FROM Opportunity "
            f"WHERE {' AND '.join(where)} ORDER BY Amount DESC NULLS LAST"
        )
        return [_opportunity(row) for row in rows]

    def fetch_org_data(self, deal_id: str) -> OrgData:
        deal_id = soql_id(deal_id)  # before any SOQL interpolation
        opportunity = self.get_opportunity(deal_id)

        account = Account(id=opportunity.account_id, name=opportunity.account_name)
        if opportunity.account_id:
            rows = self.client.query(
                "SELECT Id, Name, Industry, AnnualRevenue, BillingCity, BillingState "
                f"FROM Account WHERE Id = '{soql_id(opportunity.account_id)}'"
            )
            if rows:
                flat = flatten(rows[0])
                account = Account(
                    id=flat.get("Id") or "",
                    name=flat.get("Name") or "",
                    industry=flat.get("Industry"),
                    annual_revenue=flat.get("AnnualRevenue"),
                    billing_city=flat.get("BillingCity"),
                    billing_state=flat.get("BillingState"),
                )

        return OrgData(
            account=account,
            opportunity=opportunity,
            stage_history=self.get_opportunity_history(deal_id),
            contact_roles=self.get_contact_roles(deal_id),
            activities=self.get_activity_timeline(deal_id),
        )
