"""Agents page: choose where to send a field agent, watch it work, see what it brought back."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import func, select

from parse.agents import registry_edit, runner, scout
from parse.agents.meta import DESTS, METHODS, SCOUT, SCOUT_TOPICS, suggestions
from parse.agents.methods import method_for
from parse.db import session
from parse.models import Signal, Source

router = APIRouter()

def _source_cards(s) -> dict[str, list[dict]]:
    counts = dict(s.execute(select(Signal.source_id, func.count()).group_by(Signal.source_id)).all())
    out: dict[str, list[dict]] = {}
    for d in DESTS:
        cards = []
        for x in runner.sources_for(d["kind"], s):
            blocked = x.mvp_collect.startswith("blocked")
            m = method_for(x)
            cards.append({"id": x.source_id, "name": x.name, "tier": x.tier, "lang": x.lang, "platform": x.platform,
                          "url": x.url, "method": m, "ready": runner.ready(x) and m != "sitemap" and m != "none",
                          "blocked": blocked, "parked": not runner.ready(x) and not blocked,
                          "mode": x.mvp_collect, "status": x.status, "signals": counts.get(x.source_id, 0),
                          "bias": x.bias_note})
        out[d["kind"]] = cards
    return out


@router.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    from parse.web.app import templates   # shared Jinja env with model_list() etc.
    with session() as s:
        cards = _source_cards(s)
        suggest = suggestions(s)
    news = [c for c in cards["web"] if not c["blocked"]]
    return templates.TemplateResponse(request, "agents.html", {
        "scout": SCOUT, "suggest": suggest, "topics": SCOUT_TOPICS, "news": news, "news_ready": sum(1 for c in news if c["ready"]),
        "methods": METHODS, "accounts": scout.accounts(), "busy": scout.busy(), "runs": runner.recent()})


# ---------------------------------------------------------------- browser scout API
@router.post("/api/scout/start")
async def scout_start(request: Request):
    b = await request.json()
    try:
        run_id = scout.start(str(b.get("platform", "")), str(b.get("target") or ""), str(b.get("topic") or ""),
                             limit=int(b.get("limit") or 10), headed=bool(b.get("headed", True)))
    except scout.Busy as e:
        raise HTTPException(409, str(e))
    except (ValueError, scout.Refused) as e:
        raise HTTPException(400, str(e))
    return {"run_id": run_id}


@router.get("/api/scout/runs/{run_id}")
def scout_events(run_id: str, after: int = 0):
    ev = scout.events(run_id, max(0, after))
    if ev is None:
        raise HTTPException(404, "run not live in this process")
    return ev


@router.post("/api/scout/runs/{run_id}/stop")
def scout_stop(run_id: str):
    if not scout.stop(run_id):
        raise HTTPException(404, "run not live in this process")
    return {"ok": True}


@router.get("/api/scout/runs/{run_id}/frame.jpg")
def scout_frame(run_id: str):
    run = scout.get(run_id)
    if run is None or not run["frame"]:
        raise HTTPException(404, "no frame yet")
    return Response(run["frame"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/api/scout/runs/{run_id}/live.mjpg")
async def scout_live(run_id: str):
    """The agent browser's screen as an MJPEG stream: an <img> tag plays it with no script."""
    if scout.get(run_id) is None:
        raise HTTPException(404, "run not live in this process")

    async def frames():
        last = -1
        while True:
            run = scout.get(run_id)
            if run["frame"] is not None and run["frame_n"] != last:
                last, f = run["frame_n"], run["frame"]
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(f)).encode() + b"\r\n\r\n" + f + b"\r\n"
            if run["done"].is_set():
                return
            await asyncio.sleep(0.07)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@router.get("/api/scout/status")
def scout_status():
    w = scout._state["window"]
    return {"busy": scout.busy(), "window": w["platform"] if w else None, "accounts": scout.accounts()}


@router.post("/api/scout/window/{platform}")
def scout_window(platform: str):
    try:
        scout.open_window(platform)
    except scout.Busy as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/api/scout/window-close")
def scout_window_close():
    return {"ok": scout.close_window()}


@router.post("/api/agents/dispatch")
async def dispatch(request: Request):
    b = await request.json()
    kind = str(b.get("kind", "web"))
    if kind not in runner.KINDS:
        raise HTTPException(400, "unknown destination")
    ids = [str(x) for x in (b.get("sources") or [])][:runner.MAX_SOURCES]
    try:
        run_id = runner.start(kind, str(b.get("topic") or "").strip()[:200], ids or None,
                              limit=int(b.get("limit") or 10), origin=str(b.get("origin") or "agents-page")[:30])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"run_id": run_id}


@router.get("/api/agents/runs")
def runs():
    return {"runs": runner.recent(20)}


@router.get("/api/agents/runs/{run_id}")
def run_events(run_id: str, after: int = 0):
    ev = runner.events(run_id, max(0, after))
    if ev is None:
        raise HTTPException(404, "run not live in this process (finished runs are listed in /api/agents/runs)")
    return ev


@router.post("/api/agents/discord/channels")
async def add_discord(request: Request):
    b = await request.json()
    try:
        with session() as s:
            src = registry_edit.add_discord_channel(s, str(b.get("url", "")), str(b.get("name", "")),
                                                    int(b.get("tier", 2)), str(b.get("lang") or "en"),
                                                    str(b.get("note") or ""))
            return {"id": src.source_id, "name": src.name}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/agents/approve/{source_id}")
def approve(source_id: str):
    try:
        with session() as s:
            src = registry_edit.approve(s, source_id)
            return {"id": src.source_id, "mode": src.mvp_collect}
    except ValueError as e:
        raise HTTPException(400, str(e))
