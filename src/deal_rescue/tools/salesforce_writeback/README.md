# Tool: `salesforce_writeback`

Everything the run produced, back in the org as records. **The orchestrator's
involvement ends here** — approval and send are pure Salesforce (D8). There is no
external send path in this codebase and there must never be one.

| | |
|---|---|
| Transport | Salesforce MCP |
| Consumed by | node `publish` |
| Degrades? | **No.** A failed write-back fails the run |
| Live phase | 2.6 |
| Mode env | `SF_WRITEBACK_MODE` (falls back to `TOOL_MODE`) |

## Contract

```python
from deal_rescue.tools.salesforce_writeback import get_tool, WritebackPayload
tool = get_tool()

tool.create_rescue_writeback(WritebackPayload(
    deal_id="006...",
    score=34,
    signals=[...],
    replay_url="https://storymydata.com/app.html#s=...",
    email_draft=DraftEmail(...),
    evidence_level="full",
    audit_findings=[AuditFinding(source="web:expansion_pr_2026-09-02", ...)],
)) -> WritebackResult(opportunity_updated, rescue_result_id, draft_task_id, audit_task_ids)
```

## What lands in the org

| Record | Content |
|---|---|
| Opportunity update | `Rescue_Score__c`, `Rescue_Signals__c` (long text, one signal per line), `Replay_URL__c`, `Rescue_Evidence_Level__c` (`full` \| `org_only`) |
| Draft Task | subject `Rescue draft: <subject>` (truncated to 255), body in Description, `WhoId` = target contact, approval flag `Rescue_Draft_Approved__c = false` |
| Audit Task ×N | one per external finding: `Evidence [web:<id>] <title>` + URL, date, signal type |

Every record also carries `Rescue_Run_Key__c` = `<deal_id>-<as_of>` plus a
suffix. Marked **External Id** on Task, that turns the write-back into an upsert:
re-running a rescue the same day is idempotent instead of littering the
Opportunity with a second draft and duplicate audit records. You *will* re-run
during a demo.

`Rescue_Evidence_Level__c` carries the thin-evidence verdict into the org — a rep
must be able to tell a fully-evidenced draft from one written on CRM data alone
(D11). Full org-side field list, types and FLS: [docs/salesforce-app.md](../../../../docs/salesforce-app.md).

`audit_findings_from_state()` builds that list from `web_findings` + `transcript`
— one record per claim the agent was *allowed* to cite. That is the governance
money-shot: a rep clicks the Task and sees the source behind the sentence.

Field API names are constants at the top of `contract.py`. If the org build names
them differently, change them there — nothing else references the strings.

## The approval hop (org-side, not here)

1. Rep opens the draft Task, edits if needed, ticks `Rescue_Draft_Approved__c`.
2. A record-triggered Flow sends the email **natively** and logs completion.
3. Native activity logging, sharing rules and sender identity come free; the
   external send surface is zero (D8).

## Modes

**fake** — writes the payload to `.runs/writebacks/<deal_id>.json` and returns
plausible-shaped ids. Nothing touches an org.

**live** (Phase 2.6) — `build_request()` (pure, unit-tested) already produces the
MCP body; only `_call()` needs the `langchain_mcp_adapters` session. The
integration user needs *create* on Task and *update* on the three Opportunity
fields — no delete, no send. Document the permission set in
`docs/salesforce-setup.md` when the org build starts.

## Tests

`tests/tools/test_salesforce_writeback.py`

- `audit_findings_from_state()` yields one record per web item plus one for a
  found transcript, and nothing when both degraded
- transcript findings get a Docs URL built from `doc_id`
- `build_request()` maps score/signals/replay URL onto the API-name constants and
  sets the approval flag to `false`
- `evidence_level` reaches the Opportunity for both `full` and `org_only`
- a 400-character subject is truncated to the Salesforce 255 limit
- `make_run_key()` is stable per deal per day, and every written record carries a
  unique External Id derived from it
- fake persists the payload and returns one audit task id per finding
