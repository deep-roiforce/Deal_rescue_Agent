# Tools

A *tool* is one integration with one outside system. Each is a self-contained
package that can be developed, tested, documented and swapped on its own — that
is the whole point of the layout.

| Tool | Transport | Node | Degrades? | Live phase | Doc |
|---|---|---|---|---|---|
| `salesforce_reads` | Salesforce MCP | `fetch_org` | no — fatal | 2.1 | [README](../src/deal_rescue/tools/salesforce_reads/README.md) |
| `web_research` | HTTPS (Tavily) | `fetch_web` | yes | 2.2 | [README](../src/deal_rescue/tools/web_research/README.md) |
| `transcript` | Google Drive API | `fetch_transcript` | yes | 2.3 | [README](../src/deal_rescue/tools/transcript/README.md) |
| `agentforce` | MCP → Agent API | `synthesize` | no | 2.4 | [README](../src/deal_rescue/tools/agentforce/README.md) |
| `storymydata` | HTTPS `POST /api/story` | `publish` | no | 2.5 | [README](../src/deal_rescue/tools/storymydata/README.md) |
| `salesforce_writeback` | Salesforce MCP | `publish` | no | 2.6 | [README](../src/deal_rescue/tools/salesforce_writeback/README.md) |

## The five-file layout

```
tools/<name>/
  contract.py   typed request/response models + the Protocol. What others import.
  fake.py       fixture-backed implementation. No network. Phase 1.
  live.py       real adapter. Phase 2.
  tool.py       get_tool(settings) -> fake | live, by mode.
  README.md     contract, modes, how to go live, what the tests cover.
```

Nodes import `contract` and `tool.get_tool()` — **never** `fake` or `live`
directly. That single rule is what makes a tool swappable without touching the
graph.

`tests/test_registry.py` fails the build if a registered tool is missing any of
those files, or if its README lacks the Contract / Modes / Tests sections.

## Modes

Every tool reads `TOOL_MODE` (`fake` | `live`), overridden per tool:

```
TOOL_MODE=fake          # everything on fixtures — Phase 1 default
SF_MODE=live            # …except org reads
WEB_MODE=live
TRANSCRIPT_MODE=live
AGENTFORCE_MODE=live
STORYMYDATA_MODE=live
SF_WRITEBACK_MODE=live
```

This is how Phase 2 lands "one pipe at a time": flip one variable, run the
golden test, and the rest of the pipeline keeps working on fixtures.

Check what's live right now:

```bash
curl -s localhost:8000/healthz
```

## Adding a tool

1. `mkdir src/deal_rescue/tools/<name>` and create the five files.
2. Add a `ToolSpec` to `REGISTRY` in `tools/__init__.py` (`degrades` is the
   important field — it declares whether a failure ends the run).
3. Write `tests/tools/test_<name>.py`.
4. If a node consumes it, wire the node — not the graph — to `get_tool()`.

Definition of done for a live adapter (spec §10, Phase 2): the node works
against the real service **and** still degrades gracefully when the service is
down — except `fetch_org`, which fails the run by design.
