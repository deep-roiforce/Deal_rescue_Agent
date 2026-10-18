# Agentforce agent setup (Phase 2.4 — org side)

The synthesis prompt is source-controlled in
`src/deal_rescue/tools/agentforce/prompt.py` (`INSTRUCTIONS`). This file is the
copy-paste guide for standing up the org-side agent. If the two ever drift,
**prompt.py wins** — and remember the house rule: every prompt rule needs a
matching check in `validation.py`, edited together.

## How the pieces meet

```
synthesize node ──> MCP wrapper (synthesize_rescue) ──> Agentforce Agent API ──> your agent
                        │
                        └── sends ONE user message = INSTRUCTIONS + "INPUT:" + merge-fields JSON
```

The Python client (`live.py` / `render_user_message`) sends the *entire*
grounded payload in the message — the agent needs **no data access, no actions,
no Apex**. It only reads the message and answers with one JSON object. That is
deliberate: the allowlists in the payload plus the validation gate on our side
are the guardrails; the agent cannot reach anything else.

## Org steps (Agent Builder)

1. **Setup → Agentforce Agents → New Agent** (type: *Agentforce (default)* /
   API-accessible service agent — NOT an Employee agent).
   - Name: `Deal Rescue Synthesizer`
   - Description: `Synthesis step of the deal-rescue pipeline. Receives one
     grounded payload per request and returns one JSON object. No data access.`
2. **Delete/deactivate every default topic** except one custom topic:
   - Topic label: `Deal rescue synthesis`
   - Classification description: `Any message containing a deal-rescue INPUT
     payload (merge fields such as ALLOWED_STAGE_DATES, SCORE_BASE).`
   - Scope: `Only synthesize deal-rescue output JSON from the payload given in
     the user message. Never look up records, never take actions.`
   - Instructions: paste the INSTRUCTIONS block below, verbatim.
   - **No actions on the topic.** The agent must have zero actions.
3. Save, **Activate** the agent.
4. **Connected/External Client App for the Agent API**: enable the
   `sfap_api chatbot_api api` OAuth scopes (client-credentials flow is the
   simplest for a service integration). Note the consumer key/secret.
5. Find the agent's **Id (0Xx...)** on the agent record page URL.
6. In `.env`:

   ```
   AGENTFORCE_API_URL=https://api.salesforce.com/einstein/ai-agent/v1
   AGENTFORCE_AGENT_ID=0Xx...        # from step 5
   AGENTFORCE_MODE=live
   ```

   (The MCP wrapper server itself is the remaining code-side deliverable of
   Phase 2.4 — `live.py:_call_mcp` still raises ToolNotImplemented until it
   exists. Do not flip AGENTFORCE_MODE=live before that lands.)

## Retry behavior you get for free

When the validation gate rejects an answer, the orchestrator re-sends the same
payload with a trailing section:

```
Your previous answer was REJECTED for these reasons. Fix them all:
- <error 1>
- <error 2>
```

Two retries, then the run fails closed (`status: failed_validation`). Nothing
publishes on failure.

## INSTRUCTIONS (paste verbatim — keep in sync with prompt.py)

```
You are the synthesis step of a deal-rescue pipeline. You receive the CRM record
for one stalled opportunity, optional outside-world findings, an optional meeting
transcript, and a deterministic deal score that was already computed for you.

Return ONE JSON object and nothing else. No prose, no code fences.

Shape:
  milestones:   [{date, label, type, value?}]  type is one of stage|external|meeting
  table_data:   [{date, stage, amount}]
  email_draft:  {to_contact_id, to_name, subject, body, grounding_note, low_context_flag}
  deal_score:   {value, base_deterministic, llm_adjustment, signals[]}
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

You select, label and annotate. You do not compute.
```

## What a request's INPUT looks like (example, abridged)

```
INPUT:
{
  "ACCOUNT_NAME": "Northgate Stamping",
  "OPPORTUNITY_NAME": "ERP Quoting Integration Phase 2",
  "CURRENT_STAGE": "Negotiation/Review",
  "CLOSE_DATE": "2026-11-20",
  "STAGE_TABLE": [{"date": "2026-09-21", "stage": "Negotiation/Review", "amount": 310000.0}],
  "ALLOWED_STAGE_DATES": ["2026-09-21"],
  "ALLOWED_WEB_DATES": ["2026-08-18", "2026-09-05", "2026-09-12"],
  "ALLOWED_MEETING_DATES": ["2026-10-01"],
  "ALLOWED_AMOUNTS": [310000.0],
  "ALLOWED_CONTACT_IDS": ["003a500000uimFCAAY", "003a500000uilIeAAI"],
  "CONTACTS": [...], "ACTIVITIES": [...], "WEB_FINDINGS": {...}, "TRANSCRIPT": {...},
  "SCORE_BASE": 85, "SCORE_SIGNALS": ["15 days silent", "..."],
  "BOUND": 15,
  "EVIDENCE_LEVEL": "full",
  "ALLOWED_SOURCES": ["opp_history", "activities", "contacts", "web:...", "transcript:2026-10-01"],
  "PRIOR_ERRORS": []
}
```
