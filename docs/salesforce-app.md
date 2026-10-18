# Salesforce app — proposed changes

What has to exist in the org for Phase 2.1 (reads) and 2.6 (write-back + native
send). Nothing here is deployed: there is no `sf` CLI and no authenticated org on
the build machine, so this is a proposal to review, not a changeset.

Field API names below match the constants in
`tools/salesforce_writeback/contract.py`. Change them there and nothing else in
the orchestrator needs touching.

---

## 1. Where the result lives — recommendation: fields on Opportunity

Two options, and the spec leaves it to the implementer.

**Recommended for the demo — four fields on Opportunity plus Tasks.** The rep
sees the score on the record they already have open, with no related list to
scroll to and no extra object in the permission set. It is the smallest thing
that makes the demo true.

| API name | Type | Notes |
|---|---|---|
| `Rescue_Score__c` | Number(3,0) | 0–100. Put it on the highlights panel |
| `Rescue_Signals__c` | Long Text Area (4000) | One signal per line. **Not** Rich Text — the orchestrator writes `\n`-joined plain text |
| `Replay_URL__c` | URL(255) | The enriched Deal Replay |
| `Rescue_Evidence_Level__c` | Picklist | `full`, `org_only`. Drives the "low context" warning |

`Rescue_Evidence_Level__c` is new since the first pass — the thin-evidence rule
was being enforced in the pipeline but never reached the org, so a rep could not
tell a fully-evidenced draft from one written on CRM data alone. It now writes
through, and `test_evidence_level_reaches_the_org` holds it there.

**The upgrade, if asked: `Rescue_Result__c` child object.** One record per run
gives you run history, trending, and a proper related list — and the run key
below is already the natural External Id for it. Worth naming in an interview as
the production shape; not worth building for a 2–3 week demo.

## 2. Tasks — the audit trail, and the thing that makes it credible

Two kinds, both `WhatId` = the Opportunity:

- **One draft Task** — `Rescue draft: <subject>`, body in Description,
  `WhoId` = the target contact, `Rescue_Draft_Approved__c = false`.
- **One audit Task per external claim** — `Evidence [web:expansion_pr_2026-09-02]
  Meridian announces Plant 3 expansion`, with the source URL, date and signal
  type in Description.

That second list is the governance money-shot: a rep clicks a Task and sees the
source behind the sentence in the email. Do not collapse them into one summary
record — one record per claim is the whole point.

### Two fields on Task

| API name | Type | Notes |
|---|---|---|
| `Rescue_Draft_Approved__c` | Checkbox | The rep ticks this. The Flow watches it |
| `Rescue_Run_Key__c` | Text(80), **External Id**, Unique | Idempotency |

**Why the run key matters.** Re-running a rescue on the same deal previously
created a second draft and a duplicate set of audit Tasks — during a demo you
will re-run, and the Opportunity fills with clutter. Every written record now
carries `<deal_id>-<as_of>` plus a suffix (`-draft`,
`-web:expansion_pr_2026-09-02`, …). With the field marked External Id the
write-back **upserts**: re-running the same day is idempotent, running the next
day produces a clean new set. Enforced by
`test_every_written_record_carries_the_run_key`.

Task Subject is capped at 255, so the orchestrator truncates before sending
rather than letting the insert fail — `test_draft_subject_is_truncated_to_the_salesforce_limit`.

## 3. The approval Flow

Record-triggered on **Task**, `Rescue_Draft_Approved__c` changed to `true`:

1. Get the related Opportunity and Contact (`WhoId`).
2. **Send Email** action — Recipient: the Contact; Related Record Id: the
   Opportunity (this is what puts the sent email in the activity timeline under
   the right record).
3. Update the Task: `Status = Completed`, stamp a sent timestamp.

Entry criteria should also require `Rescue_Draft_Approved__c` was previously
false, so an edit to a completed Task cannot re-send.

### The two things that will bite on demo day

**Email Deliverability.** Dev orgs and fresh sandboxes ship with
*Setup → Deliverability → Access level = System email only*, which silently
drops Flow-sent email. Set it to **All email** and confirm with a real send
*before* you are recording. This is the single most common cause of "the demo
worked yesterday".

**Sender identity.** Default is the running user. For a demo that claims native
sender identity, either run the Flow as the record owner or configure an
org-wide email address — otherwise the email goes out as whoever ticked the box,
which may be you rather than the rep.

## 4. Integration user, connected app, permission set

JWT bearer flow (no interactive login, no stored password):

- Self-signed cert uploaded to a **Connected App**, "Admin approved users are
  pre-authorized", scopes `api` and `refresh_token` only — **not** `full`.
- A dedicated **integration user** (its own license, not yours), with the
  permission set below assigned, and the connected app's profile/permset
  pre-authorization pointing at it.
- Relax IP restrictions on the connected app's profile, or the JWT exchange
  fails from a laptop on a changing network.

### Permission set: `Deal_Rescue_Integration`

| Object | Perms | Why |
|---|---|---|
| Opportunity | Read, Edit | Edit limited to the four `Rescue_*`/`Replay_URL__c` fields via FLS |
| OpportunityHistory | Read | Stage/close-date changes — the rubric's input |
| OpportunityContactRole | Read | Who the email may address |
| Contact, Account | Read | Names, titles, the account for web research |
| Task | Read, Create, Edit | Draft + audit records, upsert by External Id |
| Event, EmailMessage | Read | Activity timeline for the silence/slope signals |

**No Delete anywhere. No View All / Modify All. No Apex class access.** Field
Level Security should make every standard field read-only for this user and
grant edit on exactly the four custom fields. When someone asks "what can this
agent actually do to my org", this table is the answer — keep it short enough to
screenshot.

## 5. MCP route — recommendation: thin custom wrapper

The spec leaves this open (§8.1) and it is still unverified which MCP surface the
demo org's edition exposes.

**Recommended: a thin custom MCP server** wrapping SOQL/REST, exposing exactly
the seven named tools the orchestrator already expects (`MCP_TOOLS` in
`tools/salesforce_reads/live.py`, `create_rescue_writeback` in the write-back
tool). Reasons:

- The tool surface *is* the least-privilege story. Six reads and one write, each
  with a fixed query — far easier to defend than "it has API access".
- Deterministic shapes. The orchestrator's `OrgData` contract needs
  field-history rows carrying `field ∈ {StageName, CloseDate, Amount}`; a general
  MCP server returns records and we would write the same mapping layer anyway.
- It is roughly 150 lines and fully in your control during a live demo.

**Use Salesforce's official MCP server instead if** the "zero custom middleware"
narrative matters more to the audience than the least-privilege one, and the org
edition exposes it. The mapping layer stays either way, so this is reversible —
`live.py` is the only file that changes.

## 6. Demo data — the constraint that shapes everything

`OpportunityHistory` cannot be inserted or backdated. The rubric reads stage
history for its two biggest deductions (close-date pushes, stage regression), so
a Meridian record freshly created in a dev org has **no history to score**.

Options, best first:

1. **Age the record by hand.** Perform the stage changes and close-date pushes in
   the org over a few days before recording. Real history, real dates, zero
   fiction — but it needs lead time, so start this early.
2. **Mirror object** `Rescue_Stage_History__c` seeded by a script, with
   `salesforce_reads` reading it instead of `OpportunityHistory` when present.
   Fully controllable; costs a small branch in the read tool and an honest
   footnote if anyone asks.
3. **Keep the graph on fixtures for the replay** and use the org only for the
   write-back and approval scenes. Cheapest, and closest to what the spec already
   assumes for the video.

Whichever you pick, say which one it is in the write-up. The project's whole
claim is about not fabricating data; fabricating the demo dataset silently would
be the one own-goal worth avoiding.

## 7. Deploy order

1. Fields + picklist values, both objects.
2. Permission set, FLS, assign to the integration user.
3. Connected app + cert, JWT round-trip verified with a single `get_opportunity`.
4. `SF_MODE=live`, re-run `pytest`, then `cli rescue meridian` end to end.
5. Flow last — it is the only piece that can send something to a human.

## 8. Explicitly not proposed

No Apex callouts (the in-org package's no-callout invariant is untouched), no
Platform Events, no external send path, no changes to the Deal Replay package,
and no Apex trigger for stall detection — stalls are computed in the orchestrator
by decision D1.
