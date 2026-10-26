# Manual setup checklist

Everything you have to create by hand before the live pipes can be switched on.
Work top to bottom — later steps depend on earlier ones.

**Rule on secrets:** put every key, token and password straight into `.env`
yourself. Don't paste secrets into chat. Tell me only the non-secret identifiers
marked **→ send me** below; I'll never need to see the values of anything else.

---

# Part 1 — Salesforce

## 1.1 Pick the org

A free **Developer Edition** org is the right choice: it has API access, which
Professional Edition does not.

- Sign up: <https://developer.salesforce.com/signup>
- Use a username you'll remember; it must be globally unique across all of
  Salesforce (e.g. `deep@dealrescue.demo`)

⚠ **If you want Agentforce in the same org**, don't use the plain Dev Edition —
see §5.1 before creating anything, because it's easier to start in the right org
than to migrate later.

**→ send me:** your My Domain URL (e.g. `https://orgfarm-xyz-dev-ed.develop.my.salesforce.com`)
and whether it's a Dev org or a sandbox.

## 1.2–1.6 — deploy the package instead of clicking

**The six custom fields and the permission set now ship as deployable metadata.**
Build and deploy it, and §1.2, §1.3 and §1.6 are done in one step:

```bash
pwsh salesforce/build-zip.ps1
```

Then Workbench → migration → Deploy → the zip, with Rollback on Error and Single
Package ticked. Full instructions, including what to do afterwards, are in
[../salesforce/README.md](../salesforce/README.md).

You still have to do by hand: **assign the permission set** (§1.6 last step),
**add the fields to page layouts**, and everything from §1.5 and §1.7 onward.

The sections below document what the package contains — read them if a deploy
fails, or if you'd rather click through it.

---

## 1.2 Custom fields on Opportunity

Setup → Object Manager → **Opportunity** → Fields & Relationships → New.

| Label | API name | Type | Settings |
|---|---|---|---|
| Rescue Score | `Rescue_Score__c` | Number | Length 3, Decimal places 0 |
| Rescue Signals | `Rescue_Signals__c` | Text Area (Long) | 4000 chars, 10 visible lines. **Not** Rich Text |
| Replay URL | `Replay_URL__c` | URL | — |
| Rescue Evidence Level | `Rescue_Evidence_Level__c` | Picklist | Values exactly: `full`, `org_only` |

Give the integration user's profile visibility as you go, or fix it in the
permission set at §1.5.

## 1.3 Custom fields on Task

Setup → Object Manager → **Task** → Fields & Relationships → New.

| Label | API name | Type | Settings |
|---|---|---|---|
| Rescue Draft Approved | `Rescue_Draft_Approved__c` | Checkbox | Default **unchecked** |
| Rescue Run Key | `Rescue_Run_Key__c` | Text(80) | ✅ External ID, ✅ Unique |

⚠ Two things that surprise people here:

1. **Task and Event share custom fields.** Salesforce stores these as Activity
   custom fields, so both will also appear on Event. That's normal, not a
   mistake — ignore them on Event.
2. **External ID + Unique is not optional.** Without it the write-back inserts
   instead of upserting, and re-running a rescue during a demo litters the
   Opportunity with duplicate audit records.

## 1.4 Page layouts

- Opportunity layout: add the four fields; put Rescue Score in the highlights
  panel so it's visible without scrolling.
- Task layout: add both fields. Rescue Draft Approved is the checkbox the rep
  actually ticks, so it needs to be somewhere obvious.

## 1.5 Integration user

Setup → Users → New User.

- License: **Salesforce**
- Profile: **Minimum Access – Salesforce** (or Standard User if that profile
  doesn't exist in your org)
- Username: globally unique, e.g. `integration@deepsexample.dealrescue`
- Email: your own address (activation mail lands there)

This is a separate user from you on purpose — "what can this agent do to my org"
is answered by one permission set rather than by your admin rights.

**→ send me:** the integration user's username.

## 1.6 Permission set

Setup → Permission Sets → New. Label `Deal Rescue Integration`, API name
`Deal_Rescue_Integration`.

**Object settings:**

| Object | Permissions |
|---|---|
| Opportunity | Read, Edit |
| Task | Read, Create, Edit |
| Account | Read |
| Contact | Read |
| Event | Read |
| Email Message | Read |

**No Delete on anything. No View All, no Modify All.**

**Field permissions** — grant Edit on exactly these, leave every other field
read-only:

- Opportunity: `Rescue_Score__c`, `Rescue_Signals__c`, `Replay_URL__c`,
  `Rescue_Evidence_Level__c`
- Task: `Rescue_Draft_Approved__c`, `Rescue_Run_Key__c`

**System permissions:** enable **API Enabled**. (Minimum Access profiles don't
have it, and the JWT login fails with a confusing error if it's missing.)

Then **Manage Assignments → Add Assignment →** the integration user.

⚠ You won't find OpportunityHistory or OpportunityContactRole in the object list
— they aren't separately permissionable. History follows Opportunity read access,
contact roles follow Opportunity + Contact. Nothing to do; just don't go hunting.

## 1.7 Certificate for JWT login

The orchestrator logs in with a signed token, not a password. You generate the
key pair locally and give Salesforce only the public half.

In Git Bash, from the repo root:

```bash
mkdir -p .secrets && openssl genrsa -out .secrets/server.key 2048 && openssl req -new -x509 -sha256 -days 730 -key .secrets/server.key -out .secrets/server.crt -subj "/CN=deal-rescue"
```

That leaves you `.secrets/server.key` (private — never leaves your machine, never
goes in git) and `.secrets/server.crt` (public — upload this to Salesforce).

Add `.secrets/` to `.gitignore` before you commit anything.

I can run that command for you — it creates the key on your machine and I never
read it.

## 1.8 Connected App

Setup → App Manager → **New Connected App**.

Newer orgs show **New External Client App** alongside it. Either works; the
classic Connected App has the simpler JWT path, so prefer it if offered.

- Connected App Name: `Deal Rescue Orchestrator`
- Contact Email: yours
- ✅ **Enable OAuth Settings**
- Callback URL: `http://localhost:1717/OauthRedirect` (unused by JWT, but the
  form demands one)
- ✅ **Use digital signatures** → upload `.secrets/server.crt`
- Selected OAuth Scopes:
  - Manage user data via APIs **(api)**
  - Perform requests at any time **(refresh_token, offline_access)**
- **Do not** grant Full access (full).

Save. ⚠ **Then wait 10 minutes.** Connected app changes propagate slowly and
logging in too early gives `invalid_client_id`, which looks like you typed
something wrong when you didn't.

After saving, go to **Manage → Edit Policies**:

- Permitted Users: **Admin approved users are pre-authorized**
- IP Relaxation: **Relax IP restrictions**

Then **Manage → Manage Permission Sets** → add `Deal Rescue Integration`.
Without this the pre-authorized setting blocks your own integration user.

**→ send me:** nothing. Copy the **Consumer Key** straight into `.env` as
`SF_CLIENT_ID`. Consumer Key plus your private key equals full API access, so
treat it like a password.

## 1.9 Email deliverability

Setup → Email → **Deliverability** → Access to Send Email: **All email**.

Dev orgs default to *System email only*, which makes Flow-sent email vanish with
no error. You don't need this until the approval Flow in Phase 2.6, but it costs
30 seconds now and is the classic "it worked yesterday" bug.

## 1.10 Demo data

Create the Meridian account, opportunity and three contacts, plus the five filler
deals. Shapes are in `fixtures/` — I can generate a load script once I can reach
the org.

⚠ **The stage-history problem.** Salesforce won't let you insert or backdate
OpportunityHistory, and two of the rubric's four deductions read that history. A
freshly created Meridian has nothing to score. Decide which route you want
(`docs/salesforce-app.md` §6) — the best option, aging the record by hand over
several days, is also the one that needs the most lead time.

## 1.11 What goes in `.env`

```
SF_MODE=live
SF_INSTANCE_URL=https://your-domain.my.salesforce.com
SF_CLIENT_ID=<Consumer Key>
SF_USERNAME=integration@deepsexample.dealrescue
SF_PRIVATE_KEY_PATH=.secrets/server.key
```

The JWT audience is `https://login.salesforce.com` for Dev/production orgs and
`https://test.salesforce.com` for sandboxes — I'll wire that from the org type
you tell me.

---

# Part 2 — Tavily (web research)

About five minutes.

1. Sign up at <https://tavily.com>
2. Copy the API key from the dashboard
3. Free tier is ~1,000 credits/month — far more than a demo needs

`.env`:

```
WEB_MODE=live
SEARCH_PROVIDER=tavily
SEARCH_API_KEY=<your key>
```

**→ send me:** nothing. Just say when it's in.

---

# Part 3 — Google Drive (transcript)

About twenty minutes, and the fiddliest of the non-Salesforce setups.

1. <https://console.cloud.google.com> → create a project (`deal-rescue-demo`)
2. APIs & Services → Library → enable **Google Drive API**
3. APIs & Services → Credentials → Create Credentials → **Service account**
   - Name: `deal-rescue-reader`
   - No roles needed — Drive access comes from folder sharing, not IAM
4. Open the service account → Keys → Add Key → **Create new key → JSON**
   - Save it to `.secrets/google-service-account.json`
5. In Google Drive, create a folder (e.g. `Deal Rescue Demo Transcripts`)
6. **Share that folder with the service account's email address** (it looks like
   `deal-rescue-reader@deal-rescue-demo.iam.gserviceaccount.com`) as **Viewer**.
   This is the step everyone forgets — without it the API returns an empty list
   rather than an error.
7. Create the fabricated Meridian transcript as a Google Doc in that folder.
   **The filename must contain the account name and the ISO date**, because
   that's how the lookup finds it:
   `Meridian Fabrication <> Solution Review - 2026-07-14 - Transcript`
   Content: mirror `fixtures/meridian/transcript.json`.
8. Folder ID is the last part of the folder's URL:
   `https://drive.google.com/drive/folders/`**`1AbC...`**

`.env`:

```
TRANSCRIPT_MODE=live
GOOGLE_CREDENTIALS_PATH=.secrets/google-service-account.json
GOOGLE_DRIVE_FOLDER_ID=<folder id>
```

**→ send me:** the folder ID (not a secret) and confirmation the Doc exists with
that exact filename.

---

# Part 4 — LangSmith (tracing)

About five minutes. This is what produces the trace you show in the demo, and the
cost numbers for the cost table.

1. Sign up at <https://smith.langchain.com>
2. Settings → API Keys → Create API Key

`.env`:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your key>
LANGSMITH_PROJECT=deal-rescue-agent
```

**→ send me:** nothing. This one we can verify immediately — it works on fake
data, so it's the only live pipe you can prove today.

---

# Part 5 — Agentforce

The biggest unknown, and worth reading before you create the Salesforce org in
§1.1.

## 5.1 Getting an org that actually has Agentforce

A plain Developer Edition org does **not** include Agentforce. Salesforce
publishes a separate **Agentforce Developer Edition** signup that bundles
Agentforce, Einstein and Data Cloud. Start there if you want the real thing, and
make it the same org as Part 1 — otherwise you end up maintaining demo data in
two places.

If you can't get an Agentforce-enabled org, the fallback is a **Prompt Template**
via Einstein Prompt Builder, or calling the model directly. The orchestrator
doesn't care much — the synthesis contract is the same either way — but the demo
narration ("judgment runs through Agentforce, where governance earns its cost")
depends on it being genuinely Agentforce.

**→ send me:** which of the three you ended up with — Agentforce agent, prompt
template, or neither.

## 5.2 The agent

1. Setup → **Agentforce Agents** → New Agent
2. Give it one topic whose instructions are the contents of `INSTRUCTIONS` in
   `src/deal_rescue/tools/agentforce/prompt.py` — that text is in the repo
   precisely so it's reviewable in git rather than only in Setup
3. Grounding: the merge fields the orchestrator sends are the whole input; the
   agent must not reach for org data itself

**→ send me:** the Agent ID from the agent's URL.

## 5.3 Agent API access

Agentforce's API is reached through a connected app using the **client
credentials** flow, which is a different setup from the JWT app in §1.8.

I'd rather confirm the exact scope names against current docs when we wire this
up in Phase 2.4 than have you click through something I half-remember —
Salesforce renamed several of these recently. Do §5.1 and §5.2 first; the API
wiring is a short step once the agent exists.

---

# Recommended order

| Order | Setup | Time | Why here |
|---|---|---|---|
| 1 | LangSmith (Part 4) | 5 min | Works on fake data — the only thing you can prove today |
| 2 | Decide Agentforce org (§5.1) | 10 min | Determines which org you create in §1.1 |
| 3 | Salesforce §1.1–1.9 | ~1 hour | Everything downstream needs real org data |
| 4 | Tavily (Part 2) | 5 min | Trivial, unblocks a whole pipe |
| 5 | Salesforce demo data (§1.10) | varies | **Start the stage-history aging early** |
| 6 | Google Drive (Part 3) | 20 min | Independent of everything else |
| 7 | Agentforce agent (§5.2) | 30 min | Last, and the most likely to need improvisation |
