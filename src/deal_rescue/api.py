"""FastAPI surface (spec 4.4).

    GET  /shortlist           current ranked shortlist
    POST /shortlist/refresh   run N1 now
    POST /rescue {query}      resolve a deal and run the graph (sync)
    GET  /healthz             mode check

LangSmith tracing is env-driven (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`) --
every rescue run should produce a full trace.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

log = logging.getLogger("deal_rescue.api")

from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from deal_rescue import profiles
from deal_rescue.settings import REPO_ROOT, Settings, get_settings
from deal_rescue.shortlist import (
    AmbiguousDeal,
    build_shortlist,
    load_shortlist,
    save_shortlist,
    summarize,
)


def refresh_shortlist_once(settings: Settings | None = None) -> int:
    """One D1 batch: rebuild and persist the shortlist. Returns entry count."""
    settings = settings or _settings()
    entries = build_shortlist(settings)
    save_shortlist(entries, settings)
    return len(entries)


async def _daily_refresh_loop(hours: float) -> None:
    """The every-24-hours component (D1). Failures are logged and the loop
    keeps going -- a flaky org at 3 a.m. must not kill the schedule."""
    try:
        if not load_shortlist(_settings()):  # cold start: don't show an empty list
            count = await asyncio.to_thread(refresh_shortlist_once)
            log.info("shortlist initial build: %d deals", count)
    except Exception as exc:  # noqa: BLE001
        log.warning("shortlist initial build failed: %s: %s", type(exc).__name__, exc)
    while True:
        await asyncio.sleep(hours * 3600)
        try:
            count = await asyncio.to_thread(refresh_shortlist_once)
            log.info("shortlist scheduled refresh: %d deals", count)
        except Exception as exc:  # noqa: BLE001
            log.warning("shortlist scheduled refresh failed: %s: %s", type(exc).__name__, exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    hours = _settings().shortlist_refresh_hours
    task = asyncio.create_task(_daily_refresh_loop(hours)) if hours > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Deal Rescue Agent", version="0.1.0", lifespan=_lifespan)

DASHBOARD = REPO_ROOT / "web" / "dashboard.html"


@app.get("/")
def dashboard() -> FileResponse:
    """The agent, watchable. One file, no build step.

    no-cache: the file is tiny and edited often; a stale cached copy renders a
    run with yesterday's JavaScript, which is worse than re-sending 30 KB."""
    return FileResponse(
        DASHBOARD, media_type="text/html", headers={"Cache-Control": "no-cache"}
    )


class RescueRequest(BaseModel):
    query: str


def _settings() -> Settings:
    """App config from env, hydrated with the active user's profile."""
    return profiles.apply(get_settings())


SETUP_PAGE = REPO_ROOT / "web" / "setup.html"


@app.get("/setup")
def setup_page() -> FileResponse:
    """Getting-started configuration, in the browser instead of .env."""
    return FileResponse(SETUP_PAGE, media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/setup/status")
def setup_status() -> dict[str, Any]:
    from deal_rescue import setupweb

    return setupweb.status(_settings())


@app.post("/setup/config")
def setup_config(values: dict[str, Any]) -> dict[str, Any]:
    from deal_rescue import setupweb
    from deal_rescue.settings import reset_settings_cache

    try:
        result = setupweb.apply_config(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # the running server must see the new values immediately
    reset_settings_cache()
    result["status"] = setupweb.status(_settings())
    return result


@app.post("/setup/test")
def setup_test(body: dict[str, Any]) -> dict[str, Any]:
    from deal_rescue import setupweb

    return setupweb.test_service(str(body.get("service") or ""), _settings())


@app.get("/briefs/{deal_id}")
def rescue_brief(deal_id: str) -> FileResponse:
    """The published rescue brief -- the human-readable result of a run."""
    from deal_rescue.brief import SAFE_ID

    if not SAFE_ID.match(deal_id):
        raise HTTPException(status_code=404, detail="not a deal id")
    path = _settings().state_dir / "briefs" / f"{deal_id}.html"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="no brief for this deal yet -- run a rescue first",
        )
    return FileResponse(path, media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    settings = _settings()
    return {
        "ok": True,
        "user": settings.deal_rescue_user,
        "ranking": settings.shortlist_ranking,
        "as_of": settings.today().isoformat(),
        "modes": {
            name: settings.mode_for(name).value
            for name in (
                "salesforce_reads",
                "web_research",
                "transcript",
                "agentforce",
                "storymydata",
                "salesforce_writeback",
            )
        },
    }


@app.get("/shortlist")
def get_shortlist() -> dict[str, Any]:
    entries = load_shortlist(_settings())
    return {"entries": entries, "summary": summarize(entries)}


@app.post("/shortlist/refresh")
def refresh_shortlist() -> dict[str, Any]:
    refresh_shortlist_once()
    entries = load_shortlist(_settings())
    return {"entries": entries, "summary": summarize(entries)}


@app.post("/rescue")
def rescue(request: RescueRequest) -> dict[str, Any]:
    try:
        entry = resolve_or_400(request.query)
    except AmbiguousDeal as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ambiguous deal query",
                "query": request.query,
                "candidates": [
                    {"deal_id": c["deal_id"], "account_name": c["account_name"]}
                    for c in exc.candidates
                ],
            },
        ) from exc

    # Imported here so the shortlist endpoints work without the graph extras.
    from deal_rescue.graph import run_rescue

    final_state = run_rescue(entry["deal_id"], entry["account_name"], _settings())
    return final_state


@app.get("/history")
def history(limit: int = 20) -> dict[str, Any]:
    """Recent runs + per-model aggregates from the run log (SQLite)."""
    from deal_rescue import runlog

    settings = _settings()
    return {
        "runs": runlog.recent(settings, limit=max(1, min(limit, 200))),
        "stats": runlog.stats(settings),
    }


@app.get("/auth/status")
def auth_status() -> dict[str, Any]:
    from deal_rescue import webauth

    return webauth.status(_settings())


@app.get("/auth/{provider}/start")
def auth_start(provider: str, request: Request) -> RedirectResponse:
    """The 'Sign in with ...' button. Redirects to the provider's own login."""
    from deal_rescue import webauth

    base = str(request.base_url)
    try:
        if provider == "salesforce":
            return RedirectResponse(webauth.salesforce_start(_settings(), base))
        if provider == "google":
            return RedirectResponse(webauth.google_start(_settings(), base))
    except Exception as exc:  # noqa: BLE001 -- the dashboard shows the reason
        return RedirectResponse(f"/?auth_error={quote(str(exc)[:300])}")
    return RedirectResponse(f"/?auth_error={quote('unknown provider ' + provider)}")


@app.get("/auth/{provider}/callback")
def auth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Where the provider sends the browser back. Always lands on the
    dashboard -- connected, or with the reason it is not."""
    from deal_rescue import webauth

    if error:
        return RedirectResponse(f"/?auth_error={quote(error_description or error)}")
    if not code or not state:
        return RedirectResponse(f"/?auth_error={quote('the login returned no code')}")

    try:
        if provider == "salesforce":
            webauth.salesforce_finish(_settings(), code, state)
        elif provider == "google":
            webauth.google_finish(_settings(), code, state)
        else:
            return RedirectResponse(f"/?auth_error={quote('unknown provider ' + provider)}")
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/?auth_error={quote(str(exc)[:300])}")
    return RedirectResponse(f"/?connected={provider}")


@app.get("/rescue/stream")
def rescue_stream(query: str) -> StreamingResponse:
    """One rescue run as server-sent events -- what the dashboard animates."""
    from deal_rescue.stream import rescue_events, sse

    settings = _settings()
    try:
        entry = resolve_or_400(query)
    except AmbiguousDeal as exc:
        candidates = ", ".join(c["account_name"] for c in exc.candidates) or "none"
        failed = iter([sse("error", {"message": f"ambiguous deal {query!r}; candidates: {candidates}"})])
        return StreamingResponse(failed, media_type="text/event-stream")

    return StreamingResponse(
        rescue_events(entry["deal_id"], entry["account_name"], settings),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def resolve_or_400(query: str) -> dict[str, Any]:
    from deal_rescue.shortlist import resolve_deal

    return resolve_deal(query, _settings())
