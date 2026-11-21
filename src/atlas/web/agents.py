"""Agents page: choose where to send a field agent, watch it work, see what it brought back."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import func, select

from atlas.agents import registry_edit, runner, scout
from atlas.agents.methods import method_for
from atlas.db import session
from atlas.models import Signal, Source

router = APIRouter()

# Plain-language explainer for each way Atlas reads a source. `call` is the real request an agent makes.
METHODS = {
    "wp-search": {
        "name": "Site search API", "short": "API",
        "how": "Many news sites run on WordPress, which has a public, read-only search endpoint. The agent asks it "
               "for posts that mention your topic and gets back clean JSON: title, full text and exact time.",
        "call": "GET {site}/wp-json/wp/v2/posts?search=<topic>",
        "speed": "1 request per source", "needs": "Nothing. Public and unauthenticated.",
    },
    "rss": {
        "name": "RSS feed", "short": "RSS",
        "how": "The site's feed lists its newest articles. The agent keeps the ones about Kosovo that match your "
               "topic, then opens each article page to save the full text and publish time.",
        "call": "GET {site}/feed  →  GET <each article>",
        "speed": "1 + 1 per article (2 s apart)", "needs": "Nothing. Public.",
    },
    "sitemap": {
        "name": "Sitemap (history only)", "short": "MAP",
        "how": "Sites without an API or feed publish a sitemap: a list of every URL with a date. Atlas used it "
               "for the historical backfill. It is too slow for a live agent, so agents skip these sites.",
        "call": "GET {site}/sitemap.xml",
        "speed": "Backfill only", "needs": "Nothing. Public.",
    },
    "telegram": {
        "name": "Telegram public preview", "short": "TG",
        "how": "Every public channel has a web page at t.me/s/<channel> that shows its latest posts to anyone. "
               "The agent reads that page. No Telegram account, no login, no API key.",
        "call": "GET https://t.me/s/<channel>",
        "speed": "1 request per channel", "needs": "The channel approved in the registry.",
    },
    "discord": {
        "name": "Discord bot", "short": "DC",
        "how": "Discord has no public web pages, so the agent uses Discord's official Bot API with a bot you create. "
               "It can only read channels in servers that invited the bot. Never a personal account (that breaks "
               "Discord's rules).",
        "call": "GET discord.com/api/v10/channels/<id>/messages",
        "speed": "1 request per channel", "needs": "DISCORD_BOT_TOKEN in .env, bot invited to the server.",
    },
}

DESTS = [
    {"kind": "web", "name": "News & official sites", "blurb": "Outlets, ministries, KFOR, EULEX and other sites in the registry."},
    {"kind": "telegram", "name": "Telegram", "blurb": "Public channels, read through their web preview."},
    {"kind": "discord", "name": "Discord", "blurb": "Channels your own bot has been invited to."},
]


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


# Browser scout destinations, in tab order. `suggest` is filled from the registry.
SCOUT = [
    {"kind": "telegram", "name": "Telegram", "where": "Public channels", "login": False,
     "how": "Opens t.me/s/<channel>, the public web preview anyone can see. Types your topic into the channel's "
            "search, then scrolls back through older posts.", "placeholder": "@channel or t.me/… (empty = registry sweep)"},
    {"kind": "discord", "name": "Discord", "where": "Servers you joined", "login": True,
     "how": "Opens the channel in Discord's web app with the agent browser's own account and scrolls back through "
            "the messages. It only sees servers that account joined; joining stays your job.",
     "placeholder": "https://discord.com/channels/…/…"},
    {"kind": "reddit", "name": "Reddit", "where": "Subreddits + threads", "login": False,
     "how": "Opens the subreddit's newest posts, keeps the ones on your topic, then opens the busiest threads and "
            "reads what people say in the comments. Use the visible browser: Reddit blocks hidden ones. ", "placeholder": "r/kosovo (empty = all of Reddit)"},
    {"kind": "x", "name": "X", "where": "Search + profiles", "login": True,
     "how": "Runs an X search for your topic, newest first (or a handle's posts), and scrolls the timeline. "
            "X shows nothing logged out, so log the agent browser in once.", "placeholder": "@handle (empty = all of X)"},
]
SCOUT_SUGGEST = {
    "telegram": [],
    "discord": [],
    "reddit": ["r/kosovo", "r/serbia", "r/albania", "r/balkans_irl"],
    "x": ["@NATO_KFOR", "@KryeministriKS", "@markodjuric"],
}


def _suggestions(s) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in SCOUT_SUGGEST.items()}
    for src in s.scalars(select(Source).where(Source.platform.in_(("telegram", "discord", "reddit", "x"))).order_by(Source.tier)):
        if (src.mvp_collect or "").startswith("blocked") or not src.url:
            continue
        tail = src.url.rstrip("/").rsplit("/", 1)[-1]
        label = {"telegram": f"@{tail}", "reddit": f"r/{tail}", "x": f"@{tail}", "discord": src.url}[src.platform]
        if src.source_id.endswith("_search"):
            continue
        if label.lower() not in {x.lower() for x in out[src.platform]}:
            out[src.platform].append(label)
    return {k: v[:8] for k, v in out.items()}


@router.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    from atlas.web.app import templates   # shared Jinja env with model_list() etc.
    with session() as s:
        cards = _source_cards(s)
        suggest = _suggestions(s)
    news = [c for c in cards["web"] if not c["blocked"]]
    return templates.TemplateResponse(request, "agents.html", {
        "scout": SCOUT, "suggest": suggest, "news": news, "news_ready": sum(1 for c in news if c["ready"]),
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
