"""SynthesisOutput contract (spec §6).

This is the orchestrator-internal contract. `nodes/publish.py` maps it onto
StoryMyData's actual API shape — the engine's format wins there.

`extra="forbid"` everywhere is deliberate: an agent that invents a field fails
the gate instead of quietly smuggling data downstream.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"

MilestoneType = Literal["stage", "external", "meeting"]
EvidenceLevel = Literal["full", "org_only"]


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(pattern=ISO_DATE)
    label: str = Field(min_length=1, max_length=120)
    type: MilestoneType
    value: float | None = None


class TableRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(pattern=ISO_DATE)
    stage: str
    amount: float


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_contact_id: str
    to_name: str
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    grounding_note: str = ""
    low_context_flag: bool = False


class DealScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = Field(ge=0, le=100)
    base_deterministic: int = Field(ge=0, le=100)
    llm_adjustment: int
    signals: list[str] = Field(default_factory=list)


class SynthesisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestones: list[Milestone] = Field(min_length=1)
    table_data: list[TableRow] = Field(min_length=1)
    email_draft: EmailDraft
    deal_score: DealScore
    # The model's full read of the deal and how to rescue it -- prose for the
    # account team, rendered on the published brief. Same honesty rules as the
    # email body: validation.py checks every currency figure in it.
    rescue_report: str = Field(min_length=1, max_length=4000)
    sources: list[str] = Field(min_length=1)
    evidence_level: EvidenceLevel
