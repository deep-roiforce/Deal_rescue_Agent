"""The run log: a SQLite record of every rescue and every eval.

One file, `.runs/deal_rescue.db`, stdlib only. Every run the agent makes --
dashboard, CLI, API, eval -- lands here with its outcome, score, retries,
model and timing, so "how is the agent performing" is a query, not a memory.

    python -m deal_rescue.cli history      # recent runs + per-model aggregates
    GET /history                           # same, as JSON

This is telemetry, not orchestration state: the graph never reads it, and
losing the file loses history, never correctness. (The spec's "no Postgres
checkpointing" stays true -- runs are not resumable from here.)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from deal_rescue.settings import Settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,              -- UTC ISO-8601
    kind      TEXT NOT NULL,              -- 'rescue' | 'eval'
    deal_id   TEXT,
    account   TEXT,
    provider  TEXT,
    model     TEXT,
    mode      TEXT,                       -- synthesis tool mode: live | fake
    status    TEXT,                       -- published | failed_* | pass | fail
    retries   INTEGER,
    score     INTEGER,
    base      INTEGER,
    adjustment INTEGER,
    evidence  TEXT,
    recipient TEXT,
    seconds   REAL,
    errors    TEXT                        -- JSON list: the last attempt's gate errors
);
CREATE INDEX IF NOT EXISTS runs_ts ON runs (ts);
CREATE INDEX IF NOT EXISTS runs_model ON runs (model, kind);
"""


def _connect(settings: Settings) -> sqlite3.Connection:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.state_dir / "deal_rescue.db")
    connection.executescript(SCHEMA)
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert(settings: Settings, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    holes = ", ".join(f":{key}" for key in row)
    with _connect(settings) as connection:
        connection.execute(f"INSERT INTO runs ({columns}) VALUES ({holes})", row)


def record_rescue(state: dict[str, Any], settings: Settings, seconds: float) -> None:
    """Called after every graph run. Never raises -- telemetry must not kill a run."""
    try:
        synthesis = state.get("synthesis") or {}
        score = synthesis.get("deal_score") or {}
        draft = synthesis.get("email_draft") or {}
        _insert(settings, {
            "ts": _now(),
            "kind": "rescue",
            "deal_id": state.get("deal_id"),
            "account": state.get("account_name"),
            "provider": settings.synthesis_provider,
            "model": settings.synthesis_model,
            "mode": settings.mode_for("agentforce").value,
            "status": state.get("status"),
            "retries": state.get("retries"),
            "score": score.get("value"),
            "base": score.get("base_deterministic"),
            "adjustment": score.get("llm_adjustment"),
            "evidence": synthesis.get("evidence_level"),
            "recipient": draft.get("to_name"),
            "seconds": round(seconds, 2),
            "errors": json.dumps(state.get("validation_errors") or []),
        })
    except Exception:  # noqa: BLE001 -- see docstring
        pass


def record_eval(report: dict[str, Any], settings: Settings) -> None:
    """One row per eval case result, so model comparisons are a GROUP BY."""
    try:
        for result in report.get("results", []):
            last = (result.get("attempts") or [{}])[-1]
            _insert(settings, {
                "ts": _now(),
                "kind": "eval",
                "deal_id": None,
                "account": result.get("case"),
                "provider": report.get("provider"),
                "model": report.get("model"),
                "mode": report.get("mode"),
                "status": "pass" if result.get("passed") else "fail",
                "retries": result.get("attempts_used"),
                "score": None, "base": None, "adjustment": None,
                "evidence": None, "recipient": None,
                "seconds": result.get("seconds"),
                "errors": json.dumps(last.get("errors") or []),
            })
    except Exception:  # noqa: BLE001
        pass


def last_rescues(settings: Settings) -> dict[str, dict[str, Any]]:
    """Most recent rescue per deal -- what the shortlist means by 'worked'.

    Never raises: with no database yet, every deal is simply unworked.
    """
    try:
        with _connect(settings) as connection:
            rows = connection.execute("""
                SELECT deal_id, ts, status, score FROM runs
                WHERE kind = 'rescue' AND deal_id IS NOT NULL AND id IN (
                    SELECT MAX(id) FROM runs
                    WHERE kind = 'rescue' AND deal_id IS NOT NULL
                    GROUP BY deal_id
                )
            """).fetchall()
        return {row["deal_id"]: dict(row) for row in rows}
    except Exception:  # noqa: BLE001
        return {}


def recent(settings: Settings, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(settings) as connection:
        rows = connection.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def stats(settings: Settings) -> list[dict[str, Any]]:
    """Per-model performance: the agent's report card."""
    with _connect(settings) as connection:
        rows = connection.execute("""
            SELECT model, kind, COUNT(*) AS runs,
                   SUM(CASE WHEN status IN ('published', 'pass') THEN 1 ELSE 0 END) AS ok,
                   ROUND(AVG(retries), 2)  AS avg_attempts,
                   ROUND(AVG(seconds), 1)  AS avg_seconds,
                   ROUND(AVG(score), 1)    AS avg_score
            FROM runs GROUP BY model, kind ORDER BY model, kind
        """).fetchall()
    return [dict(row) for row in rows]


def format_history(runs: list[dict[str, Any]], aggregates: list[dict[str, Any]]) -> str:
    lines = [f"  {'when (UTC)':20s} {'kind':7s} {'who':28s} {'model':22s} "
             f"{'status':18s} {'score':5s} {'try':3s} {'secs':5s}"]
    for run in runs:
        lines.append(
            f"  {(run['ts'] or '')[:19]:20s} {run['kind']:7s} "
            f"{(run['account'] or '')[:27]:28s} {(run['model'] or '')[:21]:22s} "
            f"{(run['status'] or ''):18s} {str(run['score'] or ''):5s} "
            f"{str(run['retries'] or ''):3s} {str(run['seconds'] or ''):5s}"
        )
    lines += ["", "  per-model report card:"]
    for agg in aggregates:
        rate = f"{agg['ok']}/{agg['runs']}"
        lines.append(
            f"  {(agg['model'] or '?'):24s} {agg['kind']:7s} ok {rate:7s} "
            f"avg attempts {agg['avg_attempts']}  avg {agg['avg_seconds']}s"
            + (f"  avg score {agg['avg_score']}" if agg["avg_score"] is not None else "")
        )
    return "\n".join(lines)
