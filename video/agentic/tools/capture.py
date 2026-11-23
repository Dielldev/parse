"""Capture real Parse runs for the agentic-loop film (video/agentic). Nothing here is mocked: every number, title
and frame in the film comes from these captures of the running app and its database.

  .venv/bin/python video/agentic/tools/capture.py scout     # a real browser-scout run on Telegram, every screencast frame
  .venv/bin/python video/agentic/tools/capture.py label     # run the product's Qwen labeller on the 8 items Ask cites
  .venv/bin/python video/agentic/tools/capture.py ask       # Ask with field agents on, streamed step by step, plus the agents' log
  .venv/bin/python video/agentic/tools/capture.py signals   # labelled posts, corpus counts and the canal P1 story from the DB
  .venv/bin/python video/agentic/tools/capture.py map       # the product's Kosovo map SVG

The app must be running (default http://127.0.0.1:8765) with its database. `scout` drives the product's own scout module
in this process (headless), only raising the screencast JPEG quality so the footage holds up at 1080p.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILM = ROOT / "video" / "agentic"
DATA = FILM / "data"
BASE = "http://127.0.0.1:8765"
sys.path.insert(0, str(ROOT / "src"))

QUESTION = "What happened at the Ibar-Lepenac canal?"
WINDOW = "canal_2024_11"


def save(name: str, obj) -> None:
    p = DATA / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    print("saved", p.relative_to(ROOT), f"{p.stat().st_size:,} bytes")


def post(path: str, body: dict, cookie: str = "parse_engine=retrieval"):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Cookie": cookie})
    return urllib.request.urlopen(req, timeout=300)


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.load(r)


def ask_stream(q: str, fresh: bool) -> list[dict]:
    out, t0 = [], time.monotonic()
    with post("/api/ask", {"q": q, "fresh": fresh, "window": WINDOW}) as r:
        for line in r:
            if line.strip():
                ev = json.loads(line)
                ev["_arrived_s"] = round(time.monotonic() - t0, 3)
                out.append(ev)
    return out


# ---------------------------------------------------------------- scout
def scout(targets: str = "@balkanspectator, @balkanar", topic: str = "Kosovo", limit: int = 12) -> None:
    from parse.agents import scout as sc
    src = inspect.getsource(sc._main).replace('"quality": 62', '"quality": 92')
    exec(compile(src, sc.__file__, "exec"), sc.__dict__)          # capture-only: sharper screencast frames
    fdir = FILM / "footage" / "scout"
    for old in fdir.glob("f*.jpg"):
        old.unlink()
    run_id = sc.start("telegram", targets, topic, limit=limit, headed=False)
    run = sc.get(run_id)
    frames, last = [], -1
    print("scout", run_id, "running…", flush=True)
    while not run["done"].is_set():
        n = run["frame_n"]
        if n != last and run["frame"]:
            last = n
            name = f"f{len(frames):05d}.jpg"
            (fdir / name).write_bytes(run["frame"])
            frames.append({"t": round(time.monotonic() - run["t0"], 3), "f": name})
        time.sleep(0.006)
    save("scout.json", {"run_id": run_id, "targets": targets, "topic": topic, "limit": limit, "status": run["status"],
                        "stats": run["stats"], "events": run["events"], "frames": frames})
    ev = run["events"]
    print(f"scout done: {len(frames)} frames, {len(ev)} events, status {run['status']}, "
          f"kept {len(run['signal_ids'])}, read {sum(1 for e in ev if e['t'] == 'post')}")


# ---------------------------------------------------------------- labels on the cited items
def label() -> None:
    evs = ask_stream(QUESTION, fresh=False)
    ans = next(e for e in evs if e["type"] == "answer")
    for c in ans["citations"]:
        try:
            with post(f"/api/signals/{c['id']}/model/label", {}, cookie="parse_engine=qwen") as r:
                d = json.load(r)
            print(f"[{c['n']}] {c['source']}: {d['summary']} · {d['model']} · ${d['usage'].get('usd', 0):.5f}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{c['n']}] {c['source']}: label failed: {e}", flush=True)


# ---------------------------------------------------------------- ask with field agents
def ask() -> None:
    evs = ask_stream(QUESTION, fresh=True)
    save("ask.json", {"q": QUESTION, "window": WINDOW, "fresh": True, "events": evs})
    ag = next((e for e in evs if e.get("id") == "agents"), None)
    if ag:
        run = get(f"/api/agents/runs/{ag['run_id']}?after=0")
        save("agents.json", run)
        print("agents:", ag["summary"], "·", len(run["events"]), "events")
    for e in evs:
        print(f"  {e.get('id', e['type']):10s} {e.get('ms', '')!s:>9} ms  arrived {e['_arrived_s']:>6}s  {e.get('summary', e.get('headline', ''))[:100]}")


# ---------------------------------------------------------------- signals: what the detector kept and dropped
def signals() -> None:
    from sqlalchemy import func, select
    from parse.db import session
    from parse.models import LlmOutput, Signal, Source
    with session() as s:
        total = s.scalar(select(func.count()).select_from(Signal))
        langs = dict(s.execute(select(Signal.lang, func.count()).group_by(Signal.lang)).all())
        srcs = s.scalar(select(func.count()).select_from(Source))
        rows = s.execute(select(LlmOutput, Signal, Source).join(Signal, Signal.signal_id == LlmOutput.subject_id)
                         .join(Source, Source.source_id == Signal.source_id)
                         .where(LlmOutput.stage == "teacher-label", Signal.window == WINDOW)
                         .order_by(Signal.published_at)).all()
        posts = []
        for o, sig, src in rows:
            posts.append({"id": sig.signal_id, "title": sig.title or (sig.text_original or "")[:160], "lang": sig.lang,
                          "source": src.name, "tier": src.tier, "platform": src.platform,
                          "when": sig.published_at, "model": o.model, "prompt": o.prompt_version, "usd": o.usd,
                          "out": o.output})
    save("signals.json", {"total": total, "langs": langs, "sources": srcs, "labelled": posts})
    print(f"{len(posts)} labelled posts in {WINDOW}: {sum(1 for p in posts if p['out'].get('is_threat_relevant'))} threat-relevant")


# ---------------------------------------------------------------- the product's map
async def _map() -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        await pg.goto(BASE + "/", wait_until="networkidle")
        svg = await pg.eval_on_selector("svg.kmap", "e => e.outerHTML")
        await b.close()
    (DATA / "kmap.svg.html").write_text(svg)
    print("saved kmap", len(svg))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "scout":
        scout(*sys.argv[2:3]) if len(sys.argv) > 2 else scout()
    elif cmd == "label":
        label()
    elif cmd == "ask":
        ask()
    elif cmd == "signals":
        signals()
    elif cmd == "map":
        asyncio.run(_map())
