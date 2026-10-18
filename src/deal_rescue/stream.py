"""Server-sent events for a rescue run: the agent, watchable.

LangGraph's `stream(..., stream_mode="updates")` yields one chunk per completed
node -- {node_name: partial_update}. This module turns those into SSE frames a
dashboard can animate, trimming each update to what a viewer needs: org_data
alone can be tens of kilobytes, and the browser needs counts and verdicts, not
the payload.

Event vocabulary:
  start -> which deal, who is running it
  node  -> one node finished: its name and a trimmed summary
  done  -> final status + the result panel's data
  error -> the run could not even start (unknown deal, auth, ...)
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from deal_rescue.settings import Settings
from deal_rescue.state import new_state


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def trim_update(
    node: str,
    update: dict[str, Any],
    settings: Settings | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What the dashboard shows for one finished node.

    Counts and verdicts for the pipeline graphic, plus a `detail` block the
    live feed renders so a viewer can watch what each node actually produced --
    the inner workings, not just a green light. Everything here must stay
    small: org_data alone can be tens of kilobytes.

    `settings` (the score weights) and `state` (the merged run so far) are
    optional extras that let the assemble and synthesize entries show the
    arithmetic itself -- the rubric line by line, and base + adjustment = value.
    """
    if node == "fetch_org":
        org = update.get("org_data") or {}
        if not org:
            return {"ok": False, "error": update.get("fetch_org_error")}
        opp = org.get("opportunity") or {}
        account = org.get("account") or {}
        history = org.get("stage_history") or []
        activities = org.get("activities") or []
        return {
            "ok": True,
            "account": account.get("name"),
            "history_rows": len(history),
            "contacts": len(org.get("contact_roles") or []),
            "activities": len(activities),
            "detail": {
                "opportunity": opp.get("name"),
                "stage": opp.get("stage"),
                "amount": opp.get("amount"),
                "close_date": opp.get("close_date"),
                "owner": opp.get("owner_name"),
                "created": opp.get("created_date"),
                "last_activity": opp.get("last_activity_date"),
                "account_line": " · ".join(
                    str(part) for part in (
                        account.get("industry"),
                        f"${account['annual_revenue']:,.0f} revenue"
                        if account.get("annual_revenue") else None,
                        ", ".join(
                            p for p in (account.get("billing_city"),
                                        account.get("billing_state")) if p
                        ) or None,
                    ) if part
                ),
                "contact_roles": [
                    {
                        "name": c.get("name"),
                        "role": c.get("role"),
                        "title": c.get("title"),
                        "primary": bool(c.get("is_primary")),
                    }
                    for c in (org.get("contact_roles") or [])[:5]
                ],
                # the most recent field changes and touches, newest last
                "history": [
                    {
                        "date": h.get("date"),
                        "field": h.get("field"),
                        "from": h.get("old_value"),
                        "to": h.get("new_value"),
                    }
                    for h in history[-5:]
                ],
                "recent_activities": [
                    {
                        "date": a.get("date"),
                        "kind": a.get("direction") or a.get("type"),
                        "subject": str(a.get("subject") or "")[:90],
                    }
                    for a in activities[-5:]
                ],
            },
        }

    if node == "fetch_web":
        findings = update.get("web_findings") or {}
        items = findings.get("items") or []
        return {
            "found": bool(findings.get("found")),
            "items": len(items),
            "dated": sum(1 for item in items if item.get("date")),
            "reason": findings.get("reason"),
            "detail": {
                "findings": [
                    {
                        "date": item.get("date"),
                        "title": str(item.get("title") or "")[:110],
                        "signal_type": item.get("signal_type"),
                    }
                    for item in items[:4]
                ],
            },
        }

    if node == "fetch_transcript":
        transcript = update.get("transcript") or {}
        excerpts = transcript.get("excerpts") or []
        return {
            "found": bool(transcript.get("found")),
            "meeting_date": transcript.get("meeting_date"),
            "excerpts": len(excerpts),
            "reason": transcript.get("reason"),
            "detail": {
                "doc_title": transcript.get("doc_title"),
                "quotes": [
                    {
                        "speaker": e.get("speaker"),
                        "text": str(e.get("text") or "")[:140],
                    }
                    for e in excerpts[:3]
                ],
            },
        }

    if node == "assemble":
        base = update.get("score_base") or {}
        deductions = base.get("deductions") or {}
        # The rubric, line by line. Numbers come from scoring.py's breakdown;
        # the weights name WHY each line costs what it costs (D9).
        math: list[str] = []
        if settings is not None and base.get("base") is not None:
            w = settings.score
            math.append(f"start at {w.start}")
            if deductions.get("days_silent"):
                math.append(
                    f"days silent: {base.get('days_silent')} "
                    f"(capped at {w.days_silent_cap}) × {w.days_silent_weight:g} "
                    f"= −{deductions['days_silent']:g}"
                )
            if deductions.get("close_date_pushes"):
                math.append(
                    f"close-date pushes: {base.get('close_date_pushes')} "
                    f"× {w.close_date_push_weight:g} = −{deductions['close_date_pushes']:g}"
                )
            if deductions.get("stage_regressions"):
                math.append(
                    f"stage regressions: {len(base.get('stage_regressions') or [])} "
                    f"× {w.stage_regression_weight:g} = −{deductions['stage_regressions']:g}"
                )
            if deductions.get("activity_slope"):
                math.append(
                    f"activity declining over the trailing "
                    f"{w.activity_slope_window_days * 2} days = −{deductions['activity_slope']:g}"
                )
            math.append(
                f"base = {w.start} − {sum(deductions.values()):g} "
                f"→ {base.get('base')} (clamped to 0–100)"
            )
        return {
            "base": base.get("base"),
            "signals": base.get("signals") or [],
            "deductions": deductions,
            "unknown_stages": base.get("unknown_stages") or [],
            "detail": {"math": math},
        }

    if node == "synthesize":
        synthesis = update.get("synthesis") or {}
        draft = synthesis.get("email_draft") or {}
        score = synthesis.get("deal_score") or {}
        # The agent's signals are whatever it appended AFTER the deterministic
        # ones it was handed -- those are the ones that justify the adjustment.
        base_signals = (state or {}).get("score_base", {}).get("signals") or []
        agent_signals = [
            s for s in (score.get("signals") or [])[len(base_signals):]
        ]
        return {
            "attempt": update.get("retries"),
            "detail": {
                "status": update.get("status"),
                "to_name": draft.get("to_name"),
                "subject": str(draft.get("subject") or "")[:110],
                "milestones": len(synthesis.get("milestones") or []),
                "sources": synthesis.get("sources") or [],
                "evidence_level": synthesis.get("evidence_level"),
                "score": {
                    "base": score.get("base_deterministic"),
                    "adjustment": score.get("llm_adjustment"),
                    "value": score.get("value"),
                    "bound": settings.score.llm_adjustment_bound if settings else None,
                    "agent_signals": [str(s)[:160] for s in agent_signals[:4]],
                },
            },
        }

    if node == "validate":
        errors = update.get("validation_errors") or []
        summary: dict[str, Any] = {"passed": not errors, "errors": errors}
        if state is not None and settings is not None:
            # The gate's own working set, for the "inside the gate" view: the
            # allowlists are derived exactly the way validation.py derives
            # them, so what the dashboard shows IS what the gate checked.
            from deal_rescue.nodes.synthesize import build_request
            from deal_rescue.tools.agentforce.prompt import allowed_sources
            from deal_rescue.validation import _allowed_amounts, _stage_rows

            request = build_request(state)
            org = request.org_data
            meeting_dates = {
                a.get("date") for a in org.get("activities") or []
                if a.get("direction") == "meeting"
            }
            if request.transcript.get("meeting_date"):
                meeting_dates.add(request.transcript["meeting_date"])
            summary["attempt"] = state.get("retries")
            summary["max_attempts"] = 1 + settings.max_synth_retries
            summary["allowed"] = {
                "stage_dates": sorted(
                    {r["date"] for r in _stage_rows(org) if r.get("date")}
                ),
                "web_dates": sorted({
                    i["date"] for i in request.web_findings.get("items") or []
                    if i.get("date")
                }),
                "meeting_dates": sorted(d for d in meeting_dates if d),
                "amounts": sorted(_allowed_amounts(org)),
                "contacts": [
                    c.get("name") for c in org.get("contact_roles") or []
                ],
                "sources": allowed_sources(request),
                "score_base": request.score_base.get("base"),
                "adjustment_bound": settings.score.llm_adjustment_bound,
            }
        return summary

    if node == "publish":
        return {
            "status": update.get("status"),
            "replay_url": update.get("replay_url"),
            "writeback": update.get("writeback") or {},
        }

    return {}


def final_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Everything the result panel renders once the run settles."""
    synthesis = state.get("synthesis") or {}
    score = synthesis.get("deal_score") or {}
    draft = synthesis.get("email_draft") or {}
    return {
        "status": state.get("status"),
        "retries": state.get("retries", 0),
        "deductions": (state.get("score_base") or {}).get("deductions") or {},
        "validation_errors": state.get("validation_errors") or [],
        "replay_url": state.get("replay_url"),
        "writeback": state.get("writeback") or {},
        "score": {
            "value": score.get("value"),
            "base": score.get("base_deterministic"),
            "adjustment": score.get("llm_adjustment"),
            "signals": score.get("signals") or [],
        },
        "email": {
            "to_name": draft.get("to_name"),
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "low_context": bool(draft.get("low_context_flag")),
        },
        "milestones": [
            {"date": m.get("date"), "label": m.get("label"), "type": m.get("type")}
            for m in synthesis.get("milestones") or []
        ],
        "sources": synthesis.get("sources") or [],
        "evidence_level": synthesis.get("evidence_level"),
    }


def rescue_events(
    deal_id: str, account_name: str, settings: Settings
) -> Iterator[str]:
    """Run the graph, narrating every node as it completes."""
    import time

    from deal_rescue import runlog
    from deal_rescue.graph import build_graph  # langgraph import stays optional

    started = time.monotonic()

    yield sse("start", {
        "deal_id": deal_id,
        "account_name": account_name,
        "user": settings.deal_rescue_user,
        "synthesis": {
            "mode": settings.mode_for("agentforce").value,
            "provider": settings.synthesis_provider,
            "model": settings.synthesis_model,
        },
        "modes": {
            name: settings.mode_for(name).value
            for name in ("salesforce_reads", "web_research", "transcript")
        },
    })

    graph = build_graph(settings)
    config = {"configurable": {"thread_id": f"dashboard-{deal_id}"}}
    state: dict[str, Any] = dict(new_state(deal_id, account_name))

    try:
        for chunk in graph.stream(state, config=config, stream_mode="updates"):
            for node, update in chunk.items():
                update = update or {}
                # Mirror the graph's own merge so `done` sees the whole run.
                for key, value in update.items():
                    state[key] = value
                yield sse("node", {
                    "node": node,
                    "summary": trim_update(node, update, settings, state),
                })
    except Exception as exc:  # noqa: BLE001 -- the viewer needs the reason
        yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        return

    runlog.record_rescue(state, settings, time.monotonic() - started)
    yield sse("done", final_payload(state))
