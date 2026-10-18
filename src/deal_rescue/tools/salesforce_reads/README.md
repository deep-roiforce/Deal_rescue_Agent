# Tool: `salesforce_reads`

Deterministic org reads. **This is the reliability floor** — every other input is
enrichment. If this tool fails, the run ends with `status="failed_fetch_org"` (D4).

| | |
|---|---|
| Transport | Salesforce MCP (`langchain-mcp-adapters`) |
| Consumed by | node `fetch_org` (parallel branch 1), `shortlist.py` (N1) |
| Degrades? | **No.** Failure is fatal by design |
| Live phase | 2.1 |
| Mode env | `SF_MODE` (falls back to `TOOL_MODE`) |

## Contract

```python
from deal_rescue.tools.salesforce_reads import get_tool
tool = get_tool()

tool.get_opportunity(deal_id)                        -> Opportunity
tool.get_opportunity_history(deal_id)                -> list[StageChange]
tool.get_contact_roles(deal_id)                      -> list[ContactRole]
tool.get_activity_timeline(deal_id, months=6)        -> list[Activity]
tool.list_stalled_opportunities(stall_days, as_of)   -> list[Opportunity]
tool.fetch_org_data(deal_id)                         -> OrgData      # composite
```

`OrgData.as_state()` returns the JSON-safe dict that goes into `RescueState["org_data"]`.
Dates are `datetime.date` in the models and ISO strings in state — the validation
gate compares against the ISO strings.

### `StageChange` is field-history, not just stage-history

Rows carry `field ∈ {StageName, CloseDate, Amount}`. The rubric reads all three:
`StageName` rows going backwards are regressions, `CloseDate` rows moving later are
pushes. Keep that shape when wiring the live adapter — `scoring.py` depends on it.

## Modes

**fake** (`fixtures/`) — Meridian has a full hand-authored fixture; the five filler
shortlist deals get a minimal synthetic `OrgData` so the graph runs for any of them.

**live** (Phase 2.1) — `live.py` holds the intended MCP tool names in `MCP_TOOLS`.
To finish it:

1. Stand up the MCP server (official Salesforce MCP if the org's edition has it,
   else a thin SOQL/REST wrapper exposing the five tool names).
2. Set `SF_MODE=live`, `SF_MCP_URL`, and the connected-app JWT vars.
3. Replace `LiveSalesforceReads._call` with a real `langchain_mcp_adapters` session.
4. Least-privilege permission set: read on Opportunity / OpportunityHistory /
   OpportunityContactRole / Task / Event / EmailMessage / Account. Document it in
   `docs/salesforce-setup.md` when the org work starts.

## Tests

`tests/tools/test_salesforce_reads.py`

- Meridian fixture round-trips through the pydantic contract
- `list_stalled_opportunities` respects `stall_days` and `as_of`
- unknown `deal_id` raises `ToolError` (fatal, not degraded)

## Known demo constraint

`OpportunityHistory` cannot be inserted or backdated in a real org, so the in-org
Deal Replay of fictional data shows repeating date labels. The demo video records
enriched replays from the StoryMyData **web** platform; the in-org package appears
only as the "native tier" hook shot (spec §5).
