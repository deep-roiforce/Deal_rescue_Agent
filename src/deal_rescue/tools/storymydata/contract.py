"""Typed contract for the StoryMyData platform.

VERIFIED against Story-engine `app/functions/api/story.js` (POST /api/story):

  body: {table, description?, milestones?, shape?, template?, adjustments?, target?}
  200:  {ok, url, shape, template, periods, rows|players, issues, chars}

The engine's format wins (spec 4.2 N8) -- `mapping.py` is where our
SynthesisOutput bends to it, not the other way round.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StoryMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    title: str = Field(max_length=120)
    desc: str = Field(default="", max_length=300)
    row_index: float | None = None  # exact placement; see README

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"period": self.period, "title": self.title, "desc": self.desc}
        if self.row_index is not None:
            payload["rowIndex"] = self.row_index
        return payload


class StoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str                      # TSV text -- the engine re-parses it deterministically
    description: str = ""
    milestones: list[StoryMilestone] = Field(default_factory=list)
    shape: str | None = "long"
    template: str | None = "horse-rider"
    adjustments: dict[str, Any] | None = None
    target: float | None = None

    def to_api(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "table": self.table,
            "description": self.description,
            "milestones": [m.to_api() for m in self.milestones],
        }
        if self.shape:
            body["shape"] = self.shape
        if self.template:
            body["template"] = self.template
        if self.adjustments:
            body["adjustments"] = self.adjustments
        if self.target is not None:
            body["target"] = self.target
        return body


class StoryResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool
    url: str
    shape: str | None = None
    template: str | None = None
    issues: list[Any] = Field(default_factory=list)


class StoryMyDataTool(Protocol):
    def create_story(self, request: StoryRequest) -> StoryResult: ...
