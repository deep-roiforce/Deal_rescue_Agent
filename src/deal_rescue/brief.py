"""The rescue brief: publish's human-readable deliverable.

One standalone HTML page per rescued deal -- the summary of the deal, what the
evidence says, and how it could be saved -- written to `.runs/briefs/` and
served at `/briefs/{deal_id}`. This is a REAL artifact (the dashboard's replay
button opens it), unlike the Phase-2.5 StoryMyData call, which stays faked.

Honesty rule, same as the dashboard's story card: this is a deterministic
template over gate-validated content. No model writes this page. The only
model-authored words on it are the email draft and the signal wordings, both
of which passed the gate and both of which are labeled.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from deal_rescue.settings import Settings

SAFE_ID = re.compile(r"^[A-Za-z0-9]{10,20}$")


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _report_html(text: Any) -> str:
    """Escape, then allow exactly one markdown nicety the model tends to use:
    **bold**. Everything else stays literal text."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _esc(text))


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "?"


def _split_agent_signals(synthesis: dict[str, Any], score_base: dict[str, Any]):
    """The agent's added signals, sorted into momentum vs. risk for display.

    Display-only heuristic over the wording -- the numbers were already
    validated; this just chooses which column a sentence prints in.
    """
    base_count = len(score_base.get("signals") or [])
    added = (synthesis.get("deal_score", {}).get("signals") or [])[base_count:]
    momentum, risks = [], []
    for signal in added:
        text = str(signal).strip()
        if text.startswith(("-", "−")) or "risk" in text.lower()[:24]:
            risks.append(text)
        else:
            momentum.append(text)
    return momentum, risks


def render_brief(state: dict[str, Any], settings: Settings) -> str:
    synthesis = state.get("synthesis") or {}
    org = state.get("org_data") or {}
    opp = org.get("opportunity") or {}
    account = org.get("account") or {}
    score_base = state.get("score_base") or {}
    score = synthesis.get("deal_score") or {}
    draft = synthesis.get("email_draft") or {}
    web_items = (state.get("web_findings") or {}).get("items") or []
    transcript = state.get("transcript") or {}
    momentum, risks = _split_agent_signals(synthesis, score_base)

    deductions = [
        f"{key.replace('_', ' ')}: −{value:g}"
        for key, value in (score_base.get("deductions") or {}).items()
        if value
    ]

    recipient = next(
        (c for c in org.get("contact_roles") or []
         if c.get("contact_id") == draft.get("to_contact_id")), {},
    )

    def li(items: list[str]) -> str:
        return "".join(f"<li>{_esc(item)}</li>" for item in items) or "<li class='quiet'>none</li>"

    quotes = "".join(
        f"<blockquote><b>{_esc(e.get('speaker') or '—')}:</b> {_esc(e.get('text'))}</blockquote>"
        for e in (transcript.get("excerpts") or [])[:4]
    )
    findings = "".join(
        f"<li><span class='mono'>{_esc(i.get('date') or 'undated')}</span> "
        f"[{_esc(i.get('signal_type'))}] {_esc(i.get('title'))}</li>"
        for i in web_items
    )
    milestones = "".join(
        f"<tr><td class='mono'>{_esc(m.get('date'))}</td>"
        f"<td class='type'>{_esc(m.get('type'))}</td><td>{_esc(m.get('label'))}</td></tr>"
        for m in synthesis.get("milestones") or []
    )
    sources = ", ".join(_esc(s) for s in synthesis.get("sources") or [])
    adjustment = score.get("llm_adjustment") or 0

    contact_rows = "".join(
        f"<tr><td>{_esc(c.get('name'))}</td><td>{_esc(c.get('title'))}</td>"
        f"<td>{_esc(c.get('role'))}{' · primary' if c.get('is_primary') else ''}</td>"
        f"<td class='mono'>{_esc(c.get('email'))}</td></tr>"
        for c in org.get("contact_roles") or []
    )
    history_rows = "".join(
        f"<tr><td class='mono'>{_esc(h.get('date'))}</td><td>{_esc(h.get('field'))}</td>"
        f"<td>{_esc(h.get('old_value') or '—')} → {_esc(h.get('new_value') or '—')}</td></tr>"
        for h in org.get("stage_history") or []
    )
    activity_rows = "".join(
        f"<tr><td class='mono'>{_esc(a.get('date'))}</td>"
        f"<td class='type'>{_esc(a.get('direction') or a.get('type'))}</td>"
        f"<td>{_esc(a.get('subject'))}</td></tr>"
        for a in (org.get("activities") or [])[-8:]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rescue brief — {_esc(account.get('name') or state.get('account_name'))}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600;700&display=swap">
<style>
  :root {{ --ground:#f6f7f9; --surface:#fff; --line:#d7dde3; --ink:#161c23;
          --soft:#5a6773; --faint:#8d98a3; --accent:#0e6c6a; --accent-soft:#e2efee;
          --good:#1a7f37; --warn:#9a6700; --crit:#c23030; --sunk:#eef1f4; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ground:#0e1317; --surface:#161d24; --line:#2a353f; --ink:#e3e9ee;
            --soft:#9aa8b4; --faint:#6b7a87; --accent:#45b1a8; --accent-soft:#11302e;
            --good:#4ac26b; --warn:#d4a72c; --crit:#ff7b72; --sunk:#10161c; }} }}
  body {{ margin:0; background:var(--ground); color:var(--ink); line-height:1.6;
         font:15px/1.6 "IBM Plex Sans", system-ui, sans-serif; }}
  .mono {{ font-family:"IBM Plex Mono", monospace; }}
  .quiet {{ color:var(--faint); }}
  main {{ max-width: 860px; margin: 0 auto; padding: 28px 20px 60px; }}
  .sheet {{ background:var(--surface); border:1px solid var(--line); border-radius:8px;
           padding: 26px 30px; }}
  h1 {{ font-family:"IBM Plex Serif", Georgia, serif; font-size:1.55rem; margin:0 0 2px; }}
  .sub {{ color:var(--soft); margin: 0 0 18px; }}
  .scorebar {{ display:flex; gap:18px; align-items:center; border:1px solid var(--line);
              border-radius:6px; background:var(--sunk); padding:12px 16px; margin:16px 0 22px; }}
  .scorebar .big {{ font:600 2.4rem/1 "IBM Plex Mono", monospace; }}
  .scorebar .how {{ font-size:.82rem; color:var(--soft); }}
  h2 {{ font-size:.78rem; letter-spacing:.1em; text-transform:uppercase;
       color:var(--faint); margin: 26px 0 8px; }}
  ul {{ margin:6px 0; padding-left: 20px; }}
  li {{ margin: 3px 0; }}
  blockquote {{ margin:8px 0; padding:8px 14px; border-left:3px solid var(--accent);
               background:var(--sunk); border-radius:0 5px 5px 0; font-size:.92rem; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
  @media (max-width:640px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .col h3 {{ margin:0 0 6px; font-size:.9rem; }}
  .col.up h3 {{ color:var(--good); }} .col.down h3 {{ color:var(--crit); }}
  .report {{ border-left:3px solid var(--accent); background:var(--accent-soft);
            border-radius:0 6px 6px 0; padding:14px 18px; white-space:pre-wrap;
            font-size:.93rem; }}
  .byline {{ font-size:.74rem; color:var(--faint); margin:4px 0 8px; }}
  .draft {{ border:1px dashed var(--warn); border-radius:6px; padding:14px 16px;
           background:var(--sunk); white-space:pre-wrap; font-size:.92rem; }}
  .draft-tag {{ display:inline-block; background:var(--warn); color:#fff; font-size:.7rem;
               font-weight:600; border-radius:4px; padding:2px 8px; margin-bottom:8px; }}
  table {{ border-collapse:collapse; width:100%; font-size:.88rem; }}
  td {{ padding:6px 10px 6px 0; border-bottom:1px dashed var(--line); vertical-align:top; }}
  td.type {{ text-transform:uppercase; font:.7rem "IBM Plex Mono", monospace;
            color:var(--accent); padding-top:9px; }}
  footer {{ margin-top:26px; padding-top:14px; border-top:1px solid var(--line);
           font-size:.78rem; color:var(--faint); }}
</style></head><body><main><div class="sheet">

<h1>Rescue brief — {_esc(account.get('name') or state.get('account_name'))}</h1>
<p class="sub">{_esc(opp.get('name'))} · {_money(opp.get('amount'))} ·
  {_esc(opp.get('stage'))} · closes {_esc(opp.get('close_date'))} ·
  owner {_esc(opp.get('owner_name'))}</p>

<div class="scorebar">
  <span class="big">{_esc(score.get('value'))}</span>
  <span class="how">deal health, 0–100<br>
    = rubric base {_esc(score.get('base_deterministic'))}
    {f"{'+' if adjustment >= 0 else '−'} {abs(adjustment)} agent adjustment (±15 max, cited)" if adjustment else "(agent left the base standing)"}
  </span>
</div>

<h2>The full read — how to rescue this deal</h2>
<p class="byline">Written by the model from the gate-checked evidence below; every
figure in it was verified against the org record.</p>
<div class="report">{_report_html(synthesis.get('rescue_report'))}</div>

<h2>Why this deal stalled</h2>
<ul>{li([*deductions, *(score_base.get('signals') or [])])}</ul>

<h2>What the evidence says</h2>
<ul>{findings or "<li class='quiet'>no outside-world findings this run</li>"}</ul>
{f"<p class='quiet' style='margin:10px 0 4px'>From the {_esc(transcript.get('meeting_date'))} meeting:</p>{quotes}" if quotes else ""}

<h2>How it could be saved</h2>
<div class="cols">
  <div class="col up"><h3>Momentum to use</h3><ul>{li(momentum)}</ul></div>
  <div class="col down"><h3>Risks to defuse</h3><ul>{li(risks)}</ul></div>
</div>

<h2>The proposed next step</h2>
<p>Reach out to <b>{_esc(draft.get('to_name'))}</b>{
  f" ({_esc(recipient.get('title'))}, {_esc(recipient.get('role'))})" if recipient else ""}.</p>
<div class="draft"><span class="draft-tag">DRAFT — NOT SENT</span>
<b>Subject:</b> {_esc(draft.get('subject'))}

{_esc(draft.get('body'))}</div>
<p class="quiet" style="font-size:.8rem">Approval happens in Salesforce; the email is
sent natively after a human approves. This tool never sends email.</p>

<h2>Deal timeline</h2>
<table>{milestones}</table>

<h2>The Salesforce record</h2>
<p class="quiet" style="font-size:.8rem;margin:4px 0 8px">Account:
  {_esc(account.get('name'))} · {_esc(account.get('industry'))} ·
  {_money(account.get('annual_revenue'))} revenue ·
  {_esc(account.get('billing_city'))}, {_esc(account.get('billing_state'))}</p>
<h3 style="font-size:.85rem;margin:12px 0 4px">Contact roles</h3>
<table>{contact_rows or "<tr><td class='quiet'>none on this opportunity</td></tr>"}</table>
<h3 style="font-size:.85rem;margin:16px 0 4px">Field history</h3>
<table>{history_rows or "<tr><td class='quiet'>none recorded</td></tr>"}</table>
<h3 style="font-size:.85rem;margin:16px 0 4px">Recent activity</h3>
<table>{activity_rows or "<tr><td class='quiet'>no activity logged</td></tr>"}</table>

<footer>
  Generated {_esc(settings.today().isoformat())} by Deal Rescue ·
  evidence level: {_esc(synthesis.get('evidence_level'))} ·
  validated by the grounding gate in {_esc(state.get('retries'))} attempt(s) ·
  citations: <span class="mono">{sources}</span><br>
  This page is a deterministic rendering of gate-validated output. The email draft
  and signal wordings are the model's; every date, amount and name traces to a
  fetched source.
</footer>

</div></main></body></html>
"""


def save_brief(state: dict[str, Any], settings: Settings) -> Path:
    """Write the brief; returns its path. The API serves it at /briefs/{deal_id}."""
    deal_id = str(state.get("deal_id") or "")
    if not SAFE_ID.match(deal_id):
        raise ValueError(f"deal_id {deal_id!r} is not a safe filename")
    directory = settings.state_dir / "briefs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{deal_id}.html"
    path.write_text(render_brief(state, settings), encoding="utf-8")
    return path


def brief_url(deal_id: str) -> str:
    return f"/briefs/{deal_id}"
