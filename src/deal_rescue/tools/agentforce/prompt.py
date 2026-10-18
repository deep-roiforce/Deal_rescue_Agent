"""The Agentforce prompt-template contract (D6, D11).

`build_merge_fields()` produces the grounded payload the prompt template
interpolates. Every number, date and stage name the agent is allowed to emit is
in here -- the instructions forbid inventing any others.

`INSTRUCTIONS` is the text to paste into the Agentforce prompt template /
agent topic. Keep it in the repo so the org-side artifact is reviewable in git.
"""

from __future__ import annotations

import json
from typing import Any

from deal_rescue.tools.agentforce.contract import SynthesisRequest

INSTRUCTIONS = """\
You are the synthesis step of a deal-rescue pipeline. You receive the CRM record
for one stalled opportunity, optional outside-world findings, an optional meeting
transcript, and a deterministic deal score that was already computed for you.

Return ONE JSON object and nothing else. No prose, no code fences.

Shape:
  milestones:   [{date, label, type, value?}]  type is one of stage|external|meeting
  table_data:   [{date, stage, amount}]
  email_draft:  {to_contact_id, to_name, subject, body, grounding_note, low_context_flag}
  deal_score:   {value, base_deterministic, llm_adjustment, signals[]}
  rescue_report: string
  sources:      [string]
  evidence_level: "full" | "org_only"

Hard rules -- output that breaks any of these is rejected and sent back to you:

1. NEVER invent or alter a number, a date, an amount or a stage name. Every
   stage-type milestone date must appear verbatim in ALLOWED_STAGE_DATES. Every
   external-type milestone date must appear in ALLOWED_WEB_DATES. Every
   meeting-type milestone date must appear in ALLOWED_MEETING_DATES. Every
   amount must appear in ALLOWED_AMOUNTS. table_data must reproduce
   STAGE_TABLE exactly.
2. Any currency figure in the email body must be one of ALLOWED_AMOUNTS.
3. email_draft.to_contact_id must be one of ALLOWED_CONTACT_IDS. Prefer an
   active contact; never address a contact the findings say has departed.
4. sources may only contain entries from ALLOWED_SOURCES.
5. deal_score.base_deterministic must equal SCORE_BASE exactly. You may set
   llm_adjustment anywhere in [-BOUND, +BOUND]; any nonzero adjustment requires
   a signal in signals[] that explains it. value = base_deterministic +
   llm_adjustment, clamped to 0..100. Keep the SCORE_SIGNALS entries first, in
   order, then append your own.
6. If EVIDENCE_LEVEL is "org_only": set evidence_level to "org_only", set
   low_context_flag to true, and keep the email short, factual and grounded only
   in CRM activity. Do not speculate about the customer's situation.
7. Labels are short (<= 120 chars) and written for a sales rep reading a timeline.
8. rescue_report is your full read of the deal for the account team: what the
   evidence says, where the risk sits, and a concrete rescue plan -- who to
   engage, what to send, in what order. 250-450 words of plain prose; short
   section headings are fine. Ground every statement in the INPUT; any currency
   figure in it must be one of ALLOWED_AMOUNTS; name only people who appear in
   CONTACTS, WEB_FINDINGS or TRANSCRIPT. Under "org_only" evidence, confine the
   report to CRM activity and say plainly that outside evidence is missing.

You select, label and annotate. You do not compute.
"""


def _stage_rows(org_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for change in org_data.get("stage_history", []):
        if change.get("field") != "StageName":
            continue
        rows.append(
            {
                "date": change["date"],
                "stage": change.get("new_value"),
                "amount": change.get("amount") or org_data.get("opportunity", {}).get("amount"),
            }
        )
    return rows


def allowed_sources(request: SynthesisRequest) -> list[str]:
    """The only citations the validation gate will accept."""
    sources = ["opp_history", "activities", "contacts", "account"]
    if request.transcript.get("found") and request.transcript.get("meeting_date"):
        sources.append(f"transcript:{request.transcript['meeting_date']}")
    for item in request.web_findings.get("items", []) or []:
        sources.append(f"web:{item['id']}")
    return sources


def build_merge_fields(request: SynthesisRequest) -> dict[str, Any]:
    org = request.org_data
    opp = org.get("opportunity", {})
    stage_rows = _stage_rows(org)
    amounts = sorted(
        {row["amount"] for row in stage_rows if row["amount"] is not None}
        | ({opp["amount"]} if opp.get("amount") is not None else set())
    )
    meeting_dates = [a["date"] for a in org.get("activities", []) if a.get("direction") == "meeting"]
    if request.transcript.get("meeting_date"):
        meeting_dates.append(request.transcript["meeting_date"])

    return {
        "ACCOUNT_NAME": opp.get("account_name"),
        "OPPORTUNITY_NAME": opp.get("name"),
        "CURRENT_STAGE": opp.get("stage"),
        "CLOSE_DATE": opp.get("close_date"),
        "STAGE_TABLE": stage_rows,
        "ALLOWED_STAGE_DATES": [row["date"] for row in stage_rows],
        "ALLOWED_WEB_DATES": [
            item["date"] for item in request.web_findings.get("items", []) or [] if item.get("date")
        ],
        "ALLOWED_MEETING_DATES": sorted(set(meeting_dates)),
        "ALLOWED_AMOUNTS": amounts,
        "ALLOWED_CONTACT_IDS": [c["contact_id"] for c in org.get("contact_roles", [])],
        "CONTACTS": org.get("contact_roles", []),
        "ACTIVITIES": org.get("activities", []),
        "WEB_FINDINGS": request.web_findings,
        "TRANSCRIPT": request.transcript,
        "SCORE_BASE": request.score_base.get("base"),
        "SCORE_SIGNALS": request.score_base.get("signals", []),
        "BOUND": 15,
        "EVIDENCE_LEVEL": request.evidence_level,
        "ALLOWED_SOURCES": allowed_sources(request),
        "PRIOR_ERRORS": request.prior_errors,
    }


def render_input_message(request: SynthesisRequest) -> str:
    """The per-request half of the prompt: grounded INPUT payload plus any gate
    rejections to fix. INSTRUCTIONS is the stable half -- backends that support
    a system prompt send it there (and can cache it); plain-agent backends
    prepend it (see `render_user_message`)."""
    parts = ["INPUT:", json.dumps(build_merge_fields(request), indent=2, default=str)]
    if request.prior_errors:
        parts += [
            "",
            "Your previous answer was REJECTED for these reasons. Fix them all:",
            *[f"- {err}" for err in request.prior_errors],
        ]
    return "\n".join(parts)


def render_user_message(request: SynthesisRequest) -> str:
    """What the MCP wrapper sends when the org uses a plain agent instead of a
    prompt template with typed merge fields."""
    return "\n".join([INSTRUCTIONS, "", render_input_message(request)])
