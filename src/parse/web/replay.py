"""The Agents page of the public demo: a replay over the archive. No key, no browser, no outbound request.

The real Agents page sends field agents and a browser scout to live sites. A public server must not do that for
strangers (it would be a request proxy), so here the same page runs the same steps against what the real agents already
brought back: the posts and articles in the read-only snapshot. Every card, count and link is real archived data;
nothing is fetched and nothing is stored. The page says so.

`POST /api/agents/replay` streams newline-delimited JSON events in the shapes agents.js already draws.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, or_, select

from parse.agents.meta import METHODS, SCOUT, SCOUT_TOPICS, method_of, suggestions, tags_of
from parse.db import session
from parse.dbcompat import regex_match
from parse.models import AgentRun, Signal, Source
from parse.web.ask import term_regex, terms_of

router = APIRouter()

PLATFORM_NAMES = {"telegram": "Telegram", "reddit": "Reddit", "x": "X", "discord": "Discord"}
RECORDED = ("telegram", "reddit")        # platforms the scout has real recorded posts for
READ_PER_TARGET = 22                     # posts "read" per channel in a replay
READ_PER_RUN = 48
NEWS_BATCH = 8                           # sources visited at once, like the real worker pool
MAX_SOURCES = 60
MAX_LIVE = 8                             # replays streaming at once on this instance
_live = 0
LIVE_ONLY = {"x": "X shows nothing to a logged-out browser, so a live scout needs a logged-in agent account. "
                  "The public demo has none.",
             "discord": "Discord is only readable by an account that joined the server, so it is live-only."}


def _tail(url: str | None) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def _handle(raw: str) -> str | None:
    """What the visitor typed (@name, t.me/s/name, r/name, a profile link) reduced to a bare lowercase name."""
    raw = (raw or "").strip().strip(",")
    m = re.search(r"(?:t\.me/(?:s/)?|reddit\.com/r/|(?:x|twitter)\.com/|^r/|^/r/|^@)([A-Za-z0-9_]{1,40})", raw) \
        or re.fullmatch(r"([A-Za-z0-9_]{1,40})", raw)
    return m.group(1).lower() if m else None


def _eng(sig: Signal) -> dict:
    e = sig.engagement
    return e if isinstance(e, dict) else {}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- the page
def _recent(s) -> list[dict]:
    names = {"telegram": "Telegram", "discord": "Discord", "reddit": "Reddit", "x": "X", "web": "News & official sites"}
    out = []
    for r in s.scalars(select(AgentRun).where(AgentRun.origin != "test").order_by(AgentRun.created_at.desc()).limit(12)):
        stats = r.stats or {}
        out.append({"kind_name": names.get(r.kind, r.kind) + (" · browser" if r.origin == "scout" else ""),
                    "topic": r.topic, "origin": r.origin, "sources": len(r.source_ids or []),
                    "kept": len(r.signal_ids or []),
                    "status": "interrupted" if r.status == "running" else r.status,
                    "problems": sum(1 for v in stats.values() if isinstance(v, dict) and v.get("state") in ("error", "blocked", "setup", "login")),
                    "created": r.created_at.strftime("%d %b %H:%M") if r.created_at else ""})
    return out


def _news_cards(s) -> list[dict]:
    cards = []
    for x in s.scalars(select(Source).where(Source.platform.in_(("news", "official", "mirror"))).order_by(Source.tier, Source.name)):
        if (x.mvp_collect or "").startswith("blocked"):
            continue
        m = method_of(x.platform, x.check_note, x.feed_urls, x.sitemap_urls)
        cards.append({"id": x.source_id, "name": x.name, "tier": x.tier, "lang": x.lang, "method": m,
                      "ready": x.mvp_collect == "yes" and x.status == "verified" and m in ("wp-search", "rss"),
                      "bias": x.bias_note})
    return cards


@router.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    from parse.web.app import templates
    with session() as s:
        counts = dict(s.execute(select(Signal.source_id, func.count()).where(Signal.platform.in_(RECORDED)).group_by(Signal.source_id)).all())
        suggest = suggestions(s, only=set(counts))
        # the channels and subreddits that have recorded posts are the ones a replay can open
        for kind in RECORDED:
            suggest[kind] = [f"{'@' if kind == 'telegram' else 'r/'}{_tail(x.url)}" for x in
                             s.scalars(select(Source).where(Source.platform == kind).order_by(Source.tier))
                             if x.source_id in counts]
        news = _news_cards(s)
        runs = _recent(s)
    return templates.TemplateResponse(request, "agents.html", {
        "replay": True, "scout": SCOUT, "suggest": suggest, "topics": SCOUT_TOPICS, "news": news,
        "news_ready": sum(1 for c in news if c["ready"]), "methods": METHODS, "accounts": {}, "busy": None, "runs": runs,
        "live_only": LIVE_ONLY})


@router.get("/api/agents/runs")
def runs():
    with session() as s:
        return {"runs": _recent(s)}


# ---------------------------------------------------------------- the replay script
Script = list[tuple[float, dict]]   # (seconds to wait before the event, event)


def _scout_script(platform: str, target: str, topic: str, limit: int) -> Script:
    terms = terms_of(topic) if topic else []
    pats = [re.compile(term_regex(t), re.I) for t in terms]
    ev: Script = []

    def add(wait: float, e: dict) -> None:
        ev.append((wait, e))

    with session() as s:
        srcs = list(s.scalars(select(Source).where(Source.platform == platform).order_by(Source.tier, Source.name)))
        by_handle = {_tail(x.url).lower(): x for x in srcs}
        counts = dict(s.execute(select(Signal.source_id, func.count()).where(Signal.platform == platform).group_by(Signal.source_id)).all())
        wanted = []
        for raw in re.split(r"[\s,]+", target.strip())[:8]:
            h = _handle(raw) if raw else None
            if h and h not in wanted:
                wanted.append(h)
        if wanted:
            plan = [(h, by_handle.get(h)) for h in wanted]
        else:
            pool = [x for x in srcs if (counts.get(x.source_id) if platform in RECORDED else not (x.mvp_collect or "").startswith("blocked"))]
            plan = [(_tail(x.url).lower(), x) for x in pool[:5]]
        if not plan and platform in LIVE_ONLY:
            plan = [("channel", None)]
        if not plan:
            raise ValueError("Name a channel or subreddit that has a recorded run (the chips under Where).")

        def label(h: str) -> str:
            return {"telegram": f"@{h}", "reddit": f"r/{h}"}.get(platform, f"@{h}")

        add(0.2, {"t": "start", "platform": platform, "topic": topic, "terms": terms, "headed": False, "replay": True,
                  "targets": [{"id": (x.source_id if x else f"none_{h}"), "label": label(h)} for h, x in plan]})
        add(0.5, {"t": "step", "action": "launch", "text": "Replaying a recorded run: no browser opens, nothing is fetched"})

        read_total = matched_total = 0
        tags: Counter = Counter()
        fwd: Counter = Counter()
        who: Counter = Counter()
        for h, x in plan:
            tid = x.source_id if x else f"none_{h}"
            url = {"telegram": f"https://t.me/s/{h}", "reddit": f"https://www.reddit.com/r/{h}/", "x": f"https://x.com/{h}",
                   "discord": "https://discord.com/channels/…"}[platform]
            add(0.35, {"t": "target", "target": tid, "state": "visiting", "label": label(h)})
            add(0.4, {"t": "step", "action": "goto", "text": f"Opening {label(h)}", "url": url})
            if platform in LIVE_ONLY:
                add(0.6, {"t": "target", "target": tid, "state": "login", "note": "needs a logged-in agent browser: live only"})
                add(0.1, {"t": "note", "text": LIVE_ONLY[platform]})
                continue
            if x is None or not counts.get(x.source_id):
                add(0.6, {"t": "target", "target": tid, "state": "error", "note": "no recorded run for this one in the demo"})
                continue
            add(0.1, {"t": "target_info", "target": tid, "title": x.name, "meta": f"{counts[x.source_id]} archived posts"})
            if topic:
                add(0.5, {"t": "step", "action": "type", "text": f"Searching for “{topic}”"})
            add(0.5, {"t": "step", "action": "scroll", "text": "Scrolling back through the posts"})
            rows = list(s.scalars(select(Signal).where(Signal.source_id == x.source_id)
                                  .order_by(Signal.published_at.desc()).limit(160)))
            read = kept = 0
            for sig in rows:
                if read >= READ_PER_TARGET or read_total >= READ_PER_RUN or kept >= limit:
                    break
                body = " ".join(p for p in (sig.title, sig.text_original or sig.text_en) if p)
                matched = (not pats) or any(p.search(body) for p in pats)
                if not matched and read >= 10:      # keep skimming a little, then move on, like the scout
                    continue
                read += 1
                read_total += 1
                tg = tags_of(body) if matched else []
                if matched:
                    kept += 1
                    tags.update(tg)
                    if platform != "reddit":    # reddit handles are not in the snapshot
                        who[sig.author_handle or x.name] += 1
                    if sig.forwarded_from:
                        fwd[sig.forwarded_from] += 1
                e = _eng(sig)
                hidden = platform == "reddit"
                add(0.14, {"t": "post", "target": tid, "platform": platform, "kind": "post" if sig.title or platform != "reddit" else "comment",
                           "url": sig.url, "author": "hidden in the demo" if hidden else (sig.author_handle or x.name),
                           "name": None, "title": sig.title, "text": (sig.text_original or sig.text_en or "")[:900],
                           "time": _iso(sig.published_at), "views": e.get("views"), "score": e.get("score"),
                           "replies": e.get("replies"), "reactions": e.get("reactions"), "metrics": e.get("metrics"),
                           "sub": (sig.collector or {}).get("sub") or x.name, "forwarded": sig.forwarded_from, "image": None,
                           "matched": matched, "kept": matched, "signal_id": sig.signal_id if matched else None, "tags": tg})
            matched_total += kept
            add(0.3, {"t": "step", "action": "read", "text": f"Read {read} posts, {kept} match"})
            add(0.2, {"t": "target", "target": tid, "state": "done", "note": f"{kept} matched of {read} read"})
        add(0.4, {"t": "end", "status": "done", "replay": True, "read": read_total, "matched": matched_total, "kept": matched_total,
                  "tags": tags.most_common(8), "forwarded": fwd.most_common(5), "authors": who.most_common(5)})
    return ev


def _news_script(topic: str, source_ids: list[str], limit: int) -> Script:
    terms = terms_of(topic) if topic else []
    ev: Script = []
    with session() as s:
        chosen = [x for x in s.scalars(select(Source).where(Source.source_id.in_(source_ids))
                                       .order_by(Source.tier, Source.name))
                  if x.platform in ("news", "official", "mirror")][:MAX_SOURCES]
        if not chosen:
            raise ValueError("Choose at least one site.")
        q = select(Signal.signal_id, Signal.source_id, Signal.title, Signal.published_at, Signal.lang).where(
            Signal.source_id.in_([x.source_id for x in chosen]))
        if terms:
            cols = (Signal.title, Signal.text_original, Signal.text_latin, Signal.text_en)
            q = q.where(or_(*[regex_match(c, term_regex(t)) for t in terms for c in cols]))
        found: dict[str, list] = {}
        for r in s.execute(q.order_by(Signal.published_at.desc()).limit(6000)):
            found.setdefault(r.source_id, [])
            if len(found[r.source_id]) < limit:
                found[r.source_id].append(r)
        meths = {x.source_id: method_of(x.platform, x.check_note, x.feed_urls, x.sitemap_urls) for x in chosen}
        ev.append((0.2, {"t": "start", "kind": "web", "topic": topic, "terms": terms, "replay": True,
                         "sources": [{"id": x.source_id, "name": x.name, "tier": x.tier, "platform": x.platform,
                                      "method": meths[x.source_id], "ready": True} for x in chosen]}))
        kept = 0
        for i in range(0, len(chosen), NEWS_BATCH):
            batch = chosen[i:i + NEWS_BATCH]
            for j, x in enumerate(batch):
                ev.append((0.12 if j else 0.3, {"t": "source", "source": x.source_id, "state": "visiting"}))
            for x in batch:
                ev.append((0.35, {"t": "note", "source": x.source_id,
                                  "text": "asking the search API…" if meths[x.source_id] == "wp-search" else "reading the feed…"}))
                hits = found.get(x.source_id, [])
                for r in hits:
                    kept += 1
                    ev.append((0.1, {"t": "item", "source": x.source_id, "id": r.signal_id, "title": r.title,
                                     "date": _iso(r.published_at)[:10] if r.published_at else None, "lang": r.lang}))
                ev.append((0.12, {"t": "source", "source": x.source_id, "state": "done", "kept": len(hits),
                                  "note": f"{len(hits)} in the archive" if hits else "nothing on this topic"}))
        ev.append((0.4, {"t": "end", "status": "done", "replay": True, "kept": kept}))
    return ev


async def _stream(script: Script) -> AsyncIterator[bytes]:
    global _live
    _live += 1
    at = 0.0
    try:
        for wait, e in script:
            await asyncio.sleep(wait)
            at += wait
            yield (json.dumps({**e, "at": round(at, 2)}, default=str) + "\n").encode()
    finally:
        _live -= 1


@router.post("/api/agents/replay")
async def replay(request: Request):
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(400, "bad request")
    if not isinstance(b, dict):
        raise HTTPException(400, "bad request")
    platform = str(b.get("platform", ""))[:12]
    topic = str(b.get("topic") or "").strip()[:200]
    target = str(b.get("target") or "")[:300]
    try:
        limit = max(1, min(int(b.get("limit") or 10), 25))
    except (TypeError, ValueError):
        raise HTTPException(400, "bad limit")
    if _live >= MAX_LIVE:
        raise HTTPException(503, "Several replays are running. Try again in a few seconds.")
    try:
        if platform == "web":
            ids = [str(x)[:80] for x in (b.get("sources") or []) if isinstance(x, str)][:MAX_SOURCES]
            script = await run_in_threadpool(_news_script, topic, ids, limit)
        elif platform in PLATFORM_NAMES:
            script = await run_in_threadpool(_scout_script, platform, target, topic, limit)
        else:
            raise ValueError("unknown platform")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(_stream(script), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})
