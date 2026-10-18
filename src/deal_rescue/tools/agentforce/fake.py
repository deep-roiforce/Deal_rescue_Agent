"""Deterministic stand-in for the Agentforce agent (Phase 1).

Two behaviours:

* **Meridian** -> the golden record from `fixtures/meridian/synthesis_golden.json`,
  with the score re-grounded on whatever the deterministic rubric just computed
  (so the fake can never drift from `scoring.py`).
* **Anything else** -> an honest org-only synthesis built from CRM data alone.
  That is the D11 thin-evidence path, and it is what the filler shortlist deals
  exercise.

`AGENTFORCE_FAKE_FAULT` injects a specific bad output so the validation gate and
the retry loop can be demonstrated without a live agent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from deal_rescue.tools.agentforce.contract import SynthesisRequest

MERIDIAN_DEAL_ID = "006MER0000000001"
MERIDIAN_ACCOUNT = "meridian fabrication"

# What the agent contributes on top of the deterministic signals.
MERIDIAN_LLM_SIGNALS = [
    "champion departed (web)",
    "expansion announced (web)",
    "positive intent in 2026-07-14 transcript",
]
MERIDIAN_LLM_ADJUSTMENT = -6

FAULTS = ("invented_date", "invented_source", "permanent")


def _clamp(value: int) -> int:
    return max(0, min(100, value))


class FakeAgentforce:
    def __init__(self, fixtures_dir: Path, fault: str | None = None) -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self.fault = fault or None

    # --- contract ----------------------------------------------------------
    def synthesize_rescue(self, request: SynthesisRequest) -> dict[str, Any]:
        opportunity = request.org_data.get("opportunity", {})
        # The golden record is tied to the FIXTURE, not to the account. Against
        # a live org the same account has different ids, different stage names
        # and history stamped today, so replaying the fixture would be exactly
        # the hallucination the gate exists to catch -- and it is: pointed at
        # live data the gate rejected every fixture date and contact id.
        is_fixture = opportunity.get("id") == MERIDIAN_DEAL_ID

        # The golden record cites BOTH enrichment sources, so replaying it with
        # only one present would cite evidence that was never fetched -- the
        # eval harness caught exactly that. Partial evidence takes the grounded
        # path like any other account.
        both_sources = bool(request.web_findings.get("found")) and bool(
            request.transcript.get("found")
        )
        if is_fixture and both_sources:
            output = self._meridian(request)
        else:
            output = self._grounded(request)

        first_attempt = not request.prior_errors
        if self.fault and (first_attempt or self.fault == "permanent"):
            output = self._inject_fault(output, self.fault)
        return output

    # --- variants ----------------------------------------------------------
    def _meridian(self, request: SynthesisRequest) -> dict[str, Any]:
        golden = json.loads(
            (self.fixtures_dir / "meridian" / "synthesis_golden.json").read_text(encoding="utf-8")
        )
        base = int(request.score_base.get("base", golden["deal_score"]["base_deterministic"]))
        signals = list(request.score_base.get("signals", [])) + MERIDIAN_LLM_SIGNALS
        golden["deal_score"] = {
            "value": _clamp(base + MERIDIAN_LLM_ADJUSTMENT),
            "base_deterministic": base,
            "llm_adjustment": MERIDIAN_LLM_ADJUSTMENT,
            "signals": signals,
        }
        return golden

    def _grounded(self, request: SynthesisRequest) -> dict[str, Any]:
        """A synthesis built from whatever this request actually contains.

        Works against fixtures and against a live org, because it reads the
        stage history, contacts and evidence it is handed rather than assuming
        any of them. That is the same discipline the real agent is held to, so
        this doubles as a reference implementation of the output contract.
        """
        org = request.org_data
        opp = org.get("opportunity", {})
        evidence_level = request.evidence_level

        stage_rows = [
            {
                "date": c["date"],
                "stage": c.get("new_value"),
                "amount": c.get("amount") or opp.get("amount"),
            }
            for c in org.get("stage_history", [])
            if c.get("field") == "StageName"
        ]

        milestones: list[dict[str, Any]] = []
        for index, row in enumerate(stage_rows):
            label = (
                f"Deal created - {row['stage']}" if index == 0
                else f"Moved to {row['stage']}"
            )
            milestones.append(
                {"date": row["date"], "label": label[:120], "type": "stage",
                 "value": row["amount"]}
            )

        sources = ["opp_history", "activities", "contacts"]
        llm_signals: list[str] = []

        # Outside-world milestones, only for findings that carry a date: the
        # gate checks an external milestone against the dates actually fetched.
        for item in (request.web_findings.get("items") or [])[:3]:
            if not item.get("date"):
                continue
            milestones.append({
                "date": item["date"],
                "label": str(item.get("title", ""))[:120],
                "type": "external",
            })
            sources.append(f"web:{item['id']}")
            llm_signals.append(f"{item.get('signal_type', 'news')} signal (web)")

        meeting_date = request.transcript.get("meeting_date")
        if request.transcript.get("found") and meeting_date:
            milestones.append({
                "date": meeting_date,
                "label": "Meeting on record with the buying group"[:120],
                "type": "meeting",
            })
            sources.append(f"transcript:{meeting_date}")
            llm_signals.append(f"meeting context from {meeting_date} transcript")

        milestones.sort(key=lambda m: m["date"])

        contacts = org.get("contact_roles", [])

        # Do not write to the person who left: skip inactive contacts and
        # anyone a people-change finding names. The live org marks nobody
        # inactive, so the findings are usually the only tell.
        departures = " ".join(
            f"{i.get('title', '')} {i.get('snippet', '')}".lower()
            for i in (request.web_findings.get("items") or [])
            if i.get("signal_type") == "people_change"
        )

        def reachable(contact: dict[str, Any]) -> bool:
            if contact.get("active", True) is False:
                return False
            name = str(contact.get("name") or "").strip().lower()
            return not (name and name in departures)

        target = next(
            (c for c in contacts if reachable(c)),
            next((c for c in contacts if c.get("active", True)),
                 contacts[0] if contacts else None),
        )
        first_name = str((target or {}).get("name", "there")).split()[0] if target else "there"

        base = int(request.score_base.get("base", 0))
        silent = request.score_base.get("days_silent")
        adjustment = -6 if llm_signals else 0
        amount = opp.get("amount")

        if evidence_level == "org_only":
            body = "\n".join([
                f"{first_name},", "",
                f"Circling back on {opp.get('name')}. My last note was {silent} days "
                "ago and I don't want to keep guessing at where this sits.", "",
                "Is this still on your plate, or should I close it out for now?", "",
                opp.get("owner_name") or "",
            ])
        else:
            evidence_line = next(
                (str(i.get("title", "")) for i in (request.web_findings.get("items") or [])
                 if i.get("date")),
                "recent news about your business",
            )
            amount_text = f" The ${amount:,.0f} proposal is unchanged." if amount else ""
            body = "\n".join([
                f"{first_name},", "",
                f"I saw this and thought of our conversation: {evidence_line}.", "",
                f"It has been {silent} days since we last spoke about "
                f"{opp.get('name')}.{amount_text} Worth twenty minutes to work out "
                "whether this still fits your plans?", "",
                opp.get("owner_name") or "",
            ])

        target_name = (target or {}).get("name", "the primary contact")
        evidence_bits = []
        if request.web_findings.get("found"):
            evidence_bits.append(
                "Outside signals: "
                + "; ".join(
                    str(i.get("title", "")) for i in (request.web_findings.get("items") or [])[:3]
                )
                + "."
            )
        if request.transcript.get("found") and meeting_date:
            evidence_bits.append(
                f"The {meeting_date} meeting is on record and its asks are actionable."
            )
        rescue_report = "\n".join([
            "THE READ",
            f"{opp.get('account_name')}'s \"{opp.get('name')}\" sits in "
            f"{opp.get('stage')} with {silent} days since the last touch."
            + (f" The ${amount:,.0f} proposal is unchanged." if amount else ""),
            *evidence_bits,
            "",
            "THE RESCUE PLAN",
            f"1. Re-open the thread with {target_name} using the drafted email.",
            "2. Answer the open asks from the record before being asked twice.",
            "3. Set a dated next step; silence is the pattern that got this deal here.",
        ] + ([
            "",
            "Outside evidence is missing this run: this plan is grounded in CRM "
            "activity alone.",
        ] if evidence_level == "org_only" else []))

        return {
            "milestones": milestones,
            "table_data": stage_rows,
            "email_draft": {
                "to_contact_id": (target or {}).get("contact_id", ""),
                "to_name": (target or {}).get("name", ""),
                "subject": f"Quick check on {opp.get('name')}"[:255],
                "body": body,
                "grounding_note": (
                    "CRM activity only - no external evidence available"
                    if evidence_level == "org_only"
                    else f"references: {', '.join(sources[3:])}"
                ),
                "low_context_flag": evidence_level == "org_only",
            },
            "deal_score": {
                "value": _clamp(base + adjustment),
                "base_deterministic": base,
                "llm_adjustment": adjustment,
                "signals": list(request.score_base.get("signals", [])) + llm_signals,
            },
            "rescue_report": rescue_report,
            "sources": sources,
            "evidence_level": evidence_level,
        }

    # --- fault injection (demo/test only) ----------------------------------
    def _inject_fault(self, output: dict[str, Any], fault: str) -> dict[str, Any]:
        broken = copy.deepcopy(output)
        if fault in ("invented_date", "permanent"):
            broken["milestones"].append(
                {
                    "date": "2026-08-05",
                    "label": "Budget approved internally",
                    "type": "external",
                }
            )
        if fault == "invented_source":
            broken["sources"].append("web:linkedin_scrape_2026-08-20")
        return broken
