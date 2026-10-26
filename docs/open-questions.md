# Open questions & spec deviations

Things a future session (or Deep) has to rule on. Each says what was assumed so
the build could continue, and what it would cost to change.

---

## 1. Spec conflict: the Meridian score cannot be 40 without a stage regression

**The conflict.** Spec §9 gives Meridian a clean forward stage history
(Discovery → Qualification → Proposal → Negotiation) and spec §6 gives the
golden record `base_deterministic: 40`, `value: 34`. With the §7 rubric those
cannot both be true:

```
100 − 19 (days silent) − 16 (2 close-date pushes) − 10 (declining activity) = 55
```

55 with the maximum allowed adjustment (−15) is 40, not 34. To reach a base of
40 the deal needs exactly one more 15-point deduction — a stage regression.

**What was built.** The fixture adds one: **2026-08-22, Negotiation → Proposal**,
two days after the champion departs. Arithmetic now lands exactly on the spec's
numbers:

```
100 − 19 − 16 − 15 (regression) − 10 = 40      40 + (−6) = 34   ✓
```

It also improves the demo: a stage *going backwards* is the most legible stall
signal on the replay, and it gives the animation a visible drop.

**If you'd rather keep §9's clean history**, change one of:
- the golden record's score (base 55, value ~49 with a −6 adjustment), or
- the rubric weights (e.g. close-date push 8 → 15.5 — arbitrary, don't).

Touching either means updating `fixtures/meridian/synthesis_golden.json`,
`test_scoring.py` and `test_pipeline.py` together.

---

## 2. `POST /api/story` drops `rowIndex` (upstream change needed)

`Story-engine/app/js/milestones.js` → `anchorLong()` supports exact `rowIndex`
placement, added — per its own comment — for Salesforce stage history, because
every stage change in a deal shares one year and year-grouping spreads them
evenly across the run.

But `normalizeMilestones()` in `app/functions/api/story.js` maps the array branch
to `{periodRaw, title, desc, anchorYear}` and **drops `rowIndex`**. Milestones
posted through the API therefore fall back to year anchoring.

- Fix: carry `rowIndex` through when it is a finite number (~2 lines).
- Then `VERIFY`: does `share.js` encode it into the `#s=` payload, and does the
  replay side pass it back into `anchorLong()`? If not, the enriched replay needs
  it added to the share encoding too.
- This repo already emits `rowIndex`; nothing changes on this side.

Blocking for: Phase 2.5, and for the demo video's enriched replay.

---

## 3. Which template for a deal replay?

`mapping.py` defaults to `horse-rider` (long/timeline shape). `fast-lane` also
consumes the long shape and races a pace line to a `target` — which could be
quota or the original close date. Worth one experiment before recording: a
deal that *slides backwards* may read better on Fast Lane than Horse Rider.

Unverified: the semantics of `adjustments: {primary, growth, rangeYears}` —
whether those column indices count the label column. The adapter currently sends
no `adjustments` and lets the engine auto-detect. If auto-detection picks Amount
(flat) over Stage progress, set them explicitly.

---

## 4. Salesforce MCP: official server or custom wrapper?

Spec §8.1 prefers Salesforce's official MCP server if the demo org's edition
exposes it. Still unverified — there is no `sf` CLI and no authenticated org on
the build machine. `live.py` in both Salesforce tools names the read tools and
the write tool it expects; either backing implementation satisfies them.

**Recommendation now on the table: the thin custom wrapper** — roughly 150 lines,
a tool surface that doubles as the least-privilege story, and deterministic
shapes for `OrgData`. Reasoning and the case for the official server instead are
in [salesforce-app.md](salesforce-app.md) §5. Reversible either way: `live.py` is
the only file that changes.

---

## 5. Meet REST API vs Drive-only transcript lookup

Chosen: **Drive-only** (search a folder by naming convention, export as text).
Simpler with a service account, no Meet admin scope, and spec §4.2 N5 permits it.
Revisit only if transcript file naming turns out to be unreliable in the demo
Workspace.

---

## 6. The existing Agent API client could not be found

Spec §0.3 mentions an existing external orchestrator ("~50× cheaper than
Agentforce" prompt-template system) whose Agent API client should be reused
rather than rewritten. It is not on this machine — `Story-engine`,
`storymydata-salesforce` and `Story-slack-bot` are the only related repos on the
Desktop, and none of them contains one.

`tools/agentforce/live.py` is therefore written as a fresh thin client. If that
project surfaces, replace `_call_mcp` with its client instead of duplicating it.

---

## 7. Demo-data limitation (from the spec, restated because it bites at record time)

`OpportunityHistory` cannot be inserted or backdated in a real org, so the in-org
Deal Replay of fictional data shows repeating date labels. The demo video records
enriched replays from the StoryMyData **web** platform; the in-org package
appears only as the "native tier" hook shot.
