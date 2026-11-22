"""Dispatch agents in the background and keep a live event log the web page can poll."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select

from parse.db import session
from parse.fetch import Fetcher, RobotsDisallowed
from parse.ids import new_id
from parse.models import AgentRun, Signal, Source
from parse.registry import RegistryGateError

from .methods import VISITORS, Ctx, NeedsSetup, method_for

KINDS = {
    "web": "News & official sites",
    "telegram": "Telegram channels",
    "discord": "Discord channels",
}
SCOUT_NAMES = {"telegram": "Telegram", "discord": "Discord", "reddit": "Reddit", "x": "X"}
WORKERS = 8
MAX_SOURCES = 80

_runs: dict[str, dict] = {}   # live runs in this process: events are appended while agents work
_lock = threading.Lock()


def ready(src: Source) -> bool:
    return src.mvp_collect == "yes" and src.status == "verified"


def sources_for(kind: str, s) -> list[Source]:
    q = select(Source).order_by(Source.tier, Source.name)
    if kind == "web":
        q = q.where(Source.platform.in_(("news", "official", "mirror")))
    else:
        q = q.where(Source.platform == kind)
    return list(s.scalars(q))


def plain_error(e: Exception) -> str:
    """Say what went wrong in words a non-engineer can act on."""
    name = type(e).__name__
    if name == "ConnectError":
        return "site unreachable (its address did not resolve or it refused the connection)"
    if name in ("ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout"):
        return "site too slow to answer; try again later"
    if "HTTP 403" in str(e):
        return "site refused the request (HTTP 403)"
    return f"{name}: {e}"[:300]


def _push(run: dict, ev: dict) -> None:
    with _lock:
        ev["i"] = len(run["events"])
        ev["at"] = round(time.monotonic() - run["t0"], 2)
        run["events"].append(ev)


def start(kind: str, topic: str, source_ids: list[str] | None, limit: int = 10, origin: str = "agents-page",
          fetch_full: bool = True, budget_s: float | None = None, http_timeout: float = 30.0) -> str:
    """Start a run in a background thread and return its id at once."""
    from parse.web.ask import terms_of   # same wording rules as Ask Parse

    if kind not in KINDS:
        raise ValueError(f"unknown agent kind {kind!r}")
    limit = max(1, min(int(limit), 50))
    with session() as s:
        pool = sources_for(kind, s)
        chosen = [x for x in pool if (not source_ids or x.source_id in source_ids)]
        if not source_ids:   # "all": only sources an agent can actually visit live
            chosen = [x for x in chosen if ready(x) and method_for(x) in VISITORS]
        chosen = chosen[:MAX_SOURCES]
        run_id = new_id("run", datetime.now(timezone.utc))
        s.add(AgentRun(run_id=run_id, kind=kind, topic=topic or None, source_ids=[x.source_id for x in chosen],
                       status="running", origin=origin))
    run = {"run_id": run_id, "kind": kind, "topic": topic, "status": "running", "events": [], "t0": time.monotonic(),
           "signal_ids": [], "stats": {}, "done": threading.Event()}
    with _lock:
        _runs[run_id] = run
    _push(run, {"t": "start", "kind": kind, "topic": topic, "terms": terms_of(topic) if topic else [],
                "sources": [{"id": x.source_id, "name": x.name, "tier": x.tier, "platform": x.platform,
                             "method": method_for(x), "ready": ready(x)} for x in chosen]})
    ctx_kw = dict(terms=terms_of(topic) if topic else [], limit=limit, fetch_full=fetch_full,
                  stop_at=time.monotonic() + budget_s if budget_s else None, http_timeout=http_timeout)
    threading.Thread(target=_work, args=(run, chosen, ctx_kw), daemon=True, name=f"agent-{run_id}").start()
    return run_id


def _work(run: dict, chosen: list[Source], ctx_kw: dict) -> None:
    fetcher = Fetcher(timeout=ctx_kw.pop("http_timeout"))
    def on_item(src: Source, sig: Signal) -> None:
        run["signal_ids"].append(sig.signal_id)
        _push(run, {"t": "item", "source": src.source_id, "id": sig.signal_id, "url": sig.url,
                    "title": sig.title or (sig.text_original or "")[:140], "lang": sig.lang,
                    "date": sig.published_at.strftime("%d %b %Y %H:%M") if sig.published_at else None})

    def on_note(src: Source, text: str) -> None:
        _push(run, {"t": "note", "source": src.source_id, "text": text})

    ctx = Ctx(run_id=run["run_id"], kind=run["kind"], fetcher=fetcher, on_item=on_item, on_note=on_note, **ctx_kw)

    def visit(src: Source) -> None:
        method = method_for(src)
        _push(run, {"t": "source", "source": src.source_id, "state": "visiting", "method": method})
        out = {"method": method, "seen": 0, "kept": 0}
        try:
            if ctx.late():
                out["state"], out["note"] = "skipped", "out of time"
            elif method not in VISITORS:
                out["state"], out["note"] = "skipped", "no live channel (sitemap only: covered by the backfill)"
            else:
                out["seen"], out["kept"] = VISITORS[method](ctx, src)
                out["state"] = "done"
                out["note"] = f"{out['kept']} new of {out['seen']} read"
        except RegistryGateError as e:
            out["state"], out["note"] = "blocked", "registry: " + str(e).split(": ", 1)[-1]
        except RobotsDisallowed:
            out["state"], out["note"] = "blocked", "robots.txt does not allow this page"
        except NeedsSetup as e:
            out["state"], out["note"] = "setup", str(e)
        except Exception as e:  # one broken source never stops the others
            out["state"], out["note"] = "error", plain_error(e)
        run["stats"][src.source_id] = out
        _push(run, {"t": "source", "source": src.source_id, **out})

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(visit, chosen))
        run["status"] = "done"
    except Exception as e:
        run["status"] = "failed"
        _push(run, {"t": "note", "source": None, "text": f"run failed: {e}"})
    finally:
        ctx.fetcher.client.close()
        with session() as s:
            row = s.get(AgentRun, run["run_id"])
            row.status, row.stats, row.signal_ids = run["status"], run["stats"], run["signal_ids"]
            row.finished_at = datetime.now(timezone.utc)
        _push(run, {"t": "end", "status": run["status"], "kept": len(run["signal_ids"])})
        run["done"].set()


def events(run_id: str, after: int = 0) -> dict | None:
    run = _runs.get(run_id)
    if run is None:
        return None
    with _lock:
        evs = run["events"][after:]
    return {"run_id": run_id, "status": run["status"], "events": evs, "next": after + len(evs)}


def wait(run_id: str, timeout: float) -> dict:
    run = _runs[run_id]
    run["done"].wait(timeout)
    return run


def recent(limit: int = 12) -> list[dict]:
    with session() as s:
        rows = list(s.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)))
    out = []
    for r in rows:
        live = _runs.get(r.run_id)
        if live is None and r.origin == "scout":
            from . import scout
            live = scout.get(r.run_id)
        status = live["status"] if live else ("interrupted" if r.status == "running" else r.status)
        stats = (live or {}).get("stats") or r.stats or {}
        name = (SCOUT_NAMES.get(r.kind, r.kind) + " · browser") if r.origin == "scout" else KINDS.get(r.kind, r.kind)
        out.append({"run_id": r.run_id, "kind": r.kind, "kind_name": name, "topic": r.topic,
                    "status": status, "origin": r.origin, "sources": len(r.source_ids or []),
                    "kept": len((live or {}).get("signal_ids") or r.signal_ids or []),
                    "problems": sum(1 for v in stats.values() if v.get("state") in ("error", "blocked", "setup", "login")),
                    "created": r.created_at.strftime("%d %b %H:%M") if r.created_at else ""})
    return out
