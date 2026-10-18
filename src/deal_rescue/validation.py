"""The schema gate (N7, D7).

Two layers:

1. **Shape** -- pydantic `SynthesisOutput`, `extra="forbid"`.
2. **Grounding** -- every date, amount, contact and citation in the output must
   trace back to something that was actually fetched (D6).

Returns a list of human-readable errors. Empty list = pass. The errors are fed
straight back to the agent on retry as `prior_errors`, so they are written to be
read by a model as much as by a person.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from deal_rescue.schemas import SynthesisOutput
from deal_rescue.scoring import final_score
from deal_rescue.settings import ScoreWeights
from deal_rescue.tools.agentforce.prompt import allowed_sources
from deal_rescue.tools.agentforce.contract import SynthesisRequest

# "$240K", "$240,000", "$1.2M"
CURRENCY = re.compile(r"\$\s?(?P<num>[\d,]+(?:\.\d+)?)\s?(?P<suffix>[KkMm])?")

ORG_ONLY_BODY_LIMIT = 900  # chars -- "shorter, org-grounded only" (D11)


def _money(text: str, suffix: str | None) -> float:
    value = float(text.replace(",", ""))
    if suffix and suffix.lower() == "k":
        value *= 1_000
    elif suffix and suffix.lower() == "m":
        value *= 1_000_000
    return value


def amounts_in_text(text: str) -> list[float]:
    return [_money(m.group("num"), m.group("suffix")) for m in CURRENCY.finditer(text or "")]


def _stage_rows(org_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "date": change["date"],
            "stage": change.get("new_value"),
            "amount": change.get("amount") or org_data.get("opportunity", {}).get("amount"),
        }
        for change in org_data.get("stage_history", [])
        if change.get("field") == "StageName"
    ]


def _allowed_amounts(org_data: dict[str, Any]) -> set[float]:
    amounts = {
        float(row["amount"])
        for row in _stage_rows(org_data)
        if row.get("amount") is not None
    }
    opp_amount = org_data.get("opportunity", {}).get("amount")
    if opp_amount is not None:
        amounts.add(float(opp_amount))
    return amounts


def validate_synthesis(
    synthesis: dict[str, Any] | None,
    request: SynthesisRequest,
    weights: ScoreWeights | None = None,
) -> list[str]:
    """Full gate. Empty list means the output may be published."""
    weights = weights or ScoreWeights()
    errors: list[str] = []

    # --- layer 1: shape ----------------------------------------------------
    if not isinstance(synthesis, dict):
        return ["synthesis is not a JSON object"]
    try:
        parsed = SynthesisOutput(**synthesis)
    except ValidationError as exc:
        for err in exc.errors():
            location = ".".join(str(part) for part in err["loc"])
            errors.append(f"schema: {location}: {err['msg']}")
        return errors

    org_data = request.org_data
    stage_rows = _stage_rows(org_data)
    stage_dates = {row["date"] for row in stage_rows}
    allowed_amounts = _allowed_amounts(org_data)

    web_items = request.web_findings.get("items", []) or []
    web_dates = {item["date"] for item in web_items if item.get("date")}
    meeting_dates = {
        activity["date"]
        for activity in org_data.get("activities", [])
        if activity.get("direction") == "meeting"
    }
    if request.transcript.get("meeting_date"):
        meeting_dates.add(request.transcript["meeting_date"])

    contact_ids = {c["contact_id"] for c in org_data.get("contact_roles", [])}

    # --- layer 2: grounding ------------------------------------------------
    for milestone in parsed.milestones:
        if milestone.type == "stage" and milestone.date not in stage_dates:
            errors.append(
                f"milestone '{milestone.label}': stage date {milestone.date} is not in "
                f"the opportunity stage history {sorted(stage_dates)}"
            )
        if milestone.type == "external" and milestone.date not in web_dates:
            errors.append(
                f"milestone '{milestone.label}': external date {milestone.date} matches no "
                f"web finding {sorted(web_dates) or '[]'}"
            )
        if milestone.type == "meeting" and milestone.date not in meeting_dates:
            errors.append(
                f"milestone '{milestone.label}': meeting date {milestone.date} matches no "
                f"logged meeting or transcript {sorted(meeting_dates) or '[]'}"
            )
        if milestone.value is not None and float(milestone.value) not in allowed_amounts:
            errors.append(
                f"milestone '{milestone.label}': amount {milestone.value} is not an amount "
                f"in the org record {sorted(allowed_amounts)}"
            )

    # table_data must reproduce stage history exactly
    actual = [
        {"date": row.date, "stage": row.stage, "amount": float(row.amount)}
        for row in parsed.table_data
    ]
    expected = [
        {"date": row["date"], "stage": row["stage"], "amount": float(row["amount"])}
        for row in stage_rows
        if row["amount"] is not None
    ]
    if actual != expected:
        errors.append(
            f"table_data does not match the opportunity stage history exactly. "
            f"expected {expected}, got {actual}"
        )

    # email draft
    draft = parsed.email_draft
    if draft.to_contact_id not in contact_ids:
        errors.append(
            f"email_draft.to_contact_id {draft.to_contact_id!r} is not a contact role on "
            f"this opportunity {sorted(contact_ids)}"
        )

    # Never email the person who left. The org rarely knows (contact roles have
    # no departed flag), so both sources of that fact are checked: an explicit
    # inactive marker, and a people-change web finding naming the recipient.
    # Found live: the agent emailed the departed champion, citing her own
    # departure announcement to her. The gate passed it. Now it does not.
    recipient = next(
        (c for c in org_data.get("contact_roles", [])
         if c.get("contact_id") == draft.to_contact_id),
        None,
    )
    if recipient is not None:
        recipient_name = str(recipient.get("name") or "").strip().lower()
        if recipient.get("active", True) is False:
            errors.append(
                f"email_draft addresses {recipient.get('name')}, who is marked inactive "
                "on this opportunity; address another contact role"
            )
        elif recipient_name:
            # Known limit: full-name substring match. A finding that calls the
            # recipient by a nickname ("Bob Smith" for contact "Robert Smith")
            # is missed -- that errs toward a false NEGATIVE (a departed person
            # might still be emailed), never a false rejection, because the
            # recipient itself is matched by contact ID above, not by name.
            for item in web_items:
                haystack = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
                if item.get("signal_type") == "people_change" and recipient_name in haystack:
                    errors.append(
                        f"email_draft addresses {recipient.get('name')}, but people-change "
                        f"finding web:{item.get('id')} says they have moved on; address "
                        "another contact role on this opportunity"
                    )
                    break
    for amount in amounts_in_text(draft.body):
        if amount not in allowed_amounts:
            errors.append(
                f"email_draft.body cites ${amount:,.0f}, which is not an amount in the "
                f"org record {sorted(allowed_amounts)}"
            )

    # rescue report (prompt rule 8): same honesty bar as the email body --
    # every currency figure in the prose must be an org amount.
    for amount in amounts_in_text(parsed.rescue_report):
        if amount not in allowed_amounts:
            errors.append(
                f"rescue_report cites ${amount:,.0f}, which is not an amount in the "
                f"org record {sorted(allowed_amounts)}"
            )

    # score
    score = parsed.deal_score
    base_expected = request.score_base.get("base")
    if base_expected is not None and score.base_deterministic != int(base_expected):
        errors.append(
            f"deal_score.base_deterministic must equal the computed rubric base "
            f"{int(base_expected)}, got {score.base_deterministic}"
        )
    bound = weights.llm_adjustment_bound
    if abs(score.llm_adjustment) > bound:
        errors.append(
            f"deal_score.llm_adjustment {score.llm_adjustment} exceeds the allowed "
            f"+/-{bound}"
        )
    base_signals = list(request.score_base.get("signals", []))
    if base_signals and score.signals[: len(base_signals)] != base_signals:
        errors.append(
            "deal_score.signals must start with the deterministic signals, in order: "
            f"{base_signals}"
        )
    if score.llm_adjustment != 0 and len(score.signals) <= len(base_signals):
        errors.append(
            "deal_score.llm_adjustment is nonzero but no signal was added to justify it"
        )
    expected_value = final_score(score.base_deterministic, score.llm_adjustment)
    if score.value != expected_value:
        errors.append(
            f"deal_score.value must equal base + adjustment clamped to 0..100 "
            f"({expected_value}), got {score.value}"
        )

    # sources
    permitted = set(allowed_sources(request))
    for source in parsed.sources:
        if source not in permitted:
            errors.append(
                f"source {source!r} was not among the inputs provided to synthesis "
                f"{sorted(permitted)}"
            )

    # evidence level (D11)
    expected_level = request.evidence_level
    if parsed.evidence_level != expected_level:
        errors.append(
            f"evidence_level must be {expected_level!r} for this input "
            f"(web found={bool(request.web_findings.get('found'))}, "
            f"transcript found={bool(request.transcript.get('found'))})"
        )
    if expected_level == "org_only":
        if not draft.low_context_flag:
            errors.append("evidence_level is org_only so email_draft.low_context_flag must be true")
        if len(draft.body) > ORG_ONLY_BODY_LIMIT:
            errors.append(
                f"org_only email body must stay under {ORG_ONLY_BODY_LIMIT} characters "
                f"(got {len(draft.body)}) -- no confident filler"
            )

    return errors
