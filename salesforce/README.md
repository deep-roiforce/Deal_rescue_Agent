# Deal Rescue — unmanaged metadata package

Everything the org needs for Phase 2.1 (reads) and 2.6 (write-back), as
deployable metadata. Replaces the click-by-click field creation in
[../docs/setup-checklist.md](../docs/setup-checklist.md) §1.2, §1.3 and §1.6.

**Six custom fields and one permission set. No Apex, no triggers, no callouts.**

## What's in it

| Component | Type | Why |
|---|---|---|
| `Opportunity.Rescue_Days_Silent__c` | Formula (Number) | Days since last activity — native, always current |
| `Opportunity.Rescue_Health_Score__c` | Formula (Number) | 0–100 health from org data alone — the native tier |
| `Opportunity.Rescue_Score__c` | Number(3,0) | 0–100 agent score, with reasons |
| `Opportunity.Rescue_Signals__c` | Long Text(4000) | One reason per line |
| `Opportunity.Replay_URL__c` | URL | Link to the enriched replay |
| `Opportunity.Rescue_Evidence_Level__c` | Picklist (restricted) | `full` / `org_only` |
| `Activity.Rescue_Draft_Approved__c` | Checkbox | What the rep ticks to send |
| `Activity.Rescue_Run_Key__c` | Text(80), External Id, Unique | Idempotent re-runs |
| `Deal_Rescue_Integration` | Permission Set | Least-privilege integration access |

### Native tier vs agent tier

`Rescue_Health_Score__c` is a formula: always current, costs nothing, needs no
integration. It uses only what a formula can structurally reach — last activity
date, close date, record age.

`Rescue_Score__c` is written by the agent and adds what a formula cannot see:
close-date pushes and stage regressions (both live in `OpportunityHistory`,
which formulas can't read), activity slope (no roll-up from Activity to
Opportunity), and outside-world signals.

There are three tiers, and each one sees further than the last:

| Tier | Meridian | What it can see |
|---|---|---|
| `Rescue_Health_Score__c` — formula | **81** | Last activity, close date, record age |
| `Rescue_Base_Score__c` — Apex | **40** | …plus history and activity aggregation |
| `Rescue_Score__c` — agent | **34** | …plus the outside world, with judgment |

The formula ranks Meridian 4th *healthiest* of six. The Apex rubric ranks it
worst. Same org, same second — the difference is two close-date pushes and a
stage regression, both of which live in `OpportunityHistory` where a formula
cannot follow, plus an activity slope that needs aggregation no roll-up
provides. The agent then takes 6 more points off for a champion who left the
company, which no amount of org data would ever reveal.

That progression is the demo.

### The two rubrics agree

`DealRescueScore.cls` and the orchestrator's `scoring.py` implement the same
rubric in different languages against different data sources — and both score
Meridian at **40**, with the same four signals in the same order. That is not a
coincidence to be admired; it is a property to be tested. The orchestrator
should read `Rescue_Base_Score__c` and fail loudly if its own computation
disagrees, rather than let two implementations drift apart quietly.

### Two things worth knowing before you deploy

**Task fields are Activity fields.** Salesforce doesn't allow custom fields
directly on Task or Event — they're created once on Activity and appear on both.
That's why they're `Activity.Rescue_*__c` in `package.xml` even though only Task
uses them. Seeing them on Event afterwards is expected.

**The `.object` files are partial.** They declare only the new `<fields>`, so
deploying cannot disturb existing Opportunity or Activity configuration. This is
additive metadata, not a replacement definition.

## Deploy (no Salesforce CLI needed)

Build the archive:

```bash
pwsh salesforce/build-zip.ps1
```

That writes **two** archives into `salesforce/dist/`, because the Metadata API
reads a deployment two ways and Workbench exposes the choice as a "Single
Package" checkbox that is easy to miss:

| Archive | Layout | Workbench setting |
|---|---|---|
| `deal-rescue-package-unpackaged.zip` | `unpackaged/package.xml` + folders | **Single Package UNTICKED** ← use this |
| `deal-rescue-package.zip` | `package.xml` at the root | Single Package **TICKED** |

Get it wrong and the deploy fails with **"no package.xml found"** — the manifest
is there, it's just in the shape the other mode expects.

Then:

1. Go to <https://workbench.developerforce.com> and log into your org
   (Environment: **Production** — Developer orgs count as Production here)
2. **migration → Deploy**
3. Choose `deal-rescue-package-unpackaged.zip`, tick **Rollback on Error**,
   leave **Single Package** unticked
4. Next → Deploy

Expect six `CustomField` components and one `PermissionSet`. Rollback on Error
means a partial failure leaves the org untouched.

### If you later install the Salesforce CLI

```bash
sf project deploy start --metadata-dir salesforce --target-org <alias>
```

Or convert to source format once and keep it that way:

```bash
sf project convert mdapi --root-dir salesforce --output-dir force-app
```

## After deploying

1. **Assign the permission set** — Setup → Permission Sets → Deal Rescue
   Integration → Manage Assignments → the integration user
2. **Add fields to layouts** — Rescue Score in the Opportunity highlights panel;
   Rescue Draft Approved somewhere obvious on the Task layout. Layouts are
   deliberately not in this package: overwriting a page layout you've customised
   is exactly the kind of destructive deploy an unmanaged package shouldn't do.
3. **Verify the External Id stuck** — Setup → Object Manager → Activity →
   Rescue Run Key should show *External ID* and *Unique*. Without both, the
   write-back inserts instead of upserting and re-running a demo duplicates
   every audit record.

### If the deploy fails on the two `Task.*` field permissions

Field-level security for Activity fields is addressed per entity, and Salesforce
has been inconsistent about whether that's `Task.` or `Activity.` across API
versions. If you get an error naming `Task.Rescue_Draft_Approved__c` or
`Task.Rescue_Run_Key__c`, open
`permissionsets/Deal_Rescue_Integration.permissionset`, change those two
`<field>` values from `Task.` to `Activity.`, rebuild and redeploy. Nothing else
changes.

## What's deliberately not here

**The approval Flow.** It's the one component that sends something to a human,
it's easier to build correctly in Flow Builder than to hand-author as XML, and a
broken Flow deployed silently is worse than no Flow. Build it in the UI —
design is in [../docs/salesforce-app.md](../docs/salesforce-app.md) §3.

**Page layouts** — see above.

**Demo data.** Meridian and the filler deals aren't metadata. Note the
OpportunityHistory constraint in `../docs/salesforce-app.md` §6 before seeding.

## Keeping it in sync with the orchestrator

Field API names are mirrored as constants in
`src/deal_rescue/tools/salesforce_writeback/contract.py`. Rename in both or
neither — `tests/tools/test_salesforce_writeback.py` asserts the write-back maps
onto those constants, so a rename that misses one side fails the suite rather
than silently writing to a field that doesn't exist.
