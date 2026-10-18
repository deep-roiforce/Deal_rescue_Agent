"""Typed contract for the synthesis step (D5).

The Agentforce agent is the only place judgment happens. It receives org data
verbatim, whatever enrichment survived, the deterministic score, and -- on a
retry -- the validation errors from the previous attempt so it can self-correct.

It returns *raw* JSON. Validation is deliberately a separate step
(`deal_rescue.validation`), because "the agent said so" is not the gate.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_data: dict[str, Any]
    web_findings: dict[str, Any] = Field(default_factory=lambda: {"found": False, "items": []})
    transcript: dict[str, Any] = Field(default_factory=lambda: {"found": False})
    score_base: dict[str, Any] = Field(default_factory=dict)
    prior_errors: list[str] = Field(default_factory=list)

    @property
    def account_name(self) -> str:
        return str(self.org_data.get("opportunity", {}).get("account_name", ""))

    @property
    def evidence_level(self) -> str:
        """org_only when both enrichment sources came back empty (D11)."""
        web_ok = bool(self.web_findings.get("found"))
        transcript_ok = bool(self.transcript.get("found"))
        return "full" if (web_ok or transcript_ok) else "org_only"


class AgentforceTool(Protocol):
    def synthesize_rescue(self, request: SynthesisRequest) -> dict[str, Any]:
        """Returns unvalidated SynthesisOutput-shaped JSON.

        Malformed output is a validation failure, not an exception -- raise only
        when the transport itself fails.
        """
        ...
