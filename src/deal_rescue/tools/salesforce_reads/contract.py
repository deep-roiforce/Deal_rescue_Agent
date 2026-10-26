"""Typed contract for org reads. Everything downstream imports from here."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class Account(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    industry: str | None = None
    annual_revenue: float | None = None
    billing_city: str | None = None
    billing_state: str | None = None


class Opportunity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    account_id: str
    account_name: str
    amount: float | None = None
    stage: str
    close_date: dt.date | None = None
    created_date: dt.date
    last_activity_date: dt.date | None = None
    is_closed: bool = False
    owner_name: str | None = None


class StageChange(BaseModel):
    """One OpportunityHistory / OpportunityFieldHistory row."""

    model_config = ConfigDict(extra="ignore")

    date: dt.date
    field: str  # "StageName" | "CloseDate" | "Amount"
    old_value: str | None = None
    new_value: str | None = None
    amount: float | None = None


class ContactRole(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact_id: str
    name: str
    title: str | None = None
    role: str | None = None
    email: str | None = None
    is_primary: bool = False
    active: bool = True


class Activity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: dt.date
    type: str  # Task | Email | Event
    subject: str
    direction: str | None = None  # outbound | inbound | meeting
    has_reply: bool | None = None


class OrgData(BaseModel):
    """The floor. Without this the run is dead (D4)."""

    model_config = ConfigDict(extra="ignore")

    account: Account
    opportunity: Opportunity
    stage_history: list[StageChange]
    contact_roles: list[ContactRole]
    activities: list[Activity]

    def as_state(self) -> dict[str, Any]:
        """JSON-safe dict for graph state (dates become ISO strings)."""
        return self.model_dump(mode="json")


class SalesforceReadsTool(Protocol):
    def get_opportunity(self, deal_id: str) -> Opportunity: ...

    def get_opportunity_history(self, deal_id: str) -> list[StageChange]: ...

    def get_contact_roles(self, deal_id: str) -> list[ContactRole]: ...

    def get_activity_timeline(self, deal_id: str, months: int = 6) -> list[Activity]: ...

    def list_stalled_opportunities(self, stall_days: int, as_of: dt.date) -> list[Opportunity]: ...

    def fetch_org_data(self, deal_id: str) -> OrgData: ...
