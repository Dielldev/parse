"""Snapshot real Parse UI state for the showcase video.

Opens the running Parse app (default http://127.0.0.1:8765) in headless Chromium, dark theme, 1440x900,
and saves the rendered DOM of the screens the video animates, plus the API JSON behind them and a copy
of the product stylesheets, into video/src/. Nothing here writes to the database.

  .venv/bin/python video/tools/capture.py watch
  .venv/bin/python video/tools/capture.py trace evt_...
  .venv/bin/python video/tools/capture.py ask
  .venv/bin/python video/tools/capture.py css
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video" / "src"
BASE = "http://127.0.0.1:8765"
STATIC = ROOT / "src" / "parse" / "web" / "static"


def get_json(path: str):
    with urlopen(BASE + path, timeout=60) as r:
        return json.load(r)


def save(name: str, data) -> None:
    p = OUT / "data" / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) if not isinstance(data, str) else data)
    print("saved", p.relative_to(ROOT), f"{p.stat().st_size:,} bytes")


async def page_for(p, cookies=None):
    b = await p.chromium.launch()
    ctx = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, color_scheme="dark")
    await ctx.add_init_script("try{localStorage.setItem('parse-theme','dark')}catch(e){}")
    if cookies:
        await ctx.add_cookies(cookies)
    return b, await ctx.new_page()


async def outer(pg, sel: str, all_: bool = False):
    if all_:
        return await pg.eval_on_selector_all(sel, "els => els.map(e => e.outerHTML)")
    return await pg.eval_on_selector(sel, "e => e.outerHTML")


async def watch():
    async with async_playwright() as p:
        b, pg = await page_for(p)
        await pg.goto(BASE + "/watch", wait_until="networkidle")
        await pg.wait_for_timeout(3500)
        dom = {
            "header": await outer(pg, "header.ph"),
            "ctl": await outer(pg, "section.wt-ctl"),
            "pipe": await outer(pg, "section.wt-pipe"),
            "kpis": await outer(pg, "section.wt-kpis"),
            "stories": await outer(pg, "#wt-stories article.wt-story", all_=True),
            "feed": await outer(pg, "#wt-feed"),
            "log": await outer(pg, "#wt-log"),
            "accounts": await outer(pg, "#wt-acc"),
        }
        save("watch_dom.json", dom)
        await pg.screenshot(path=str(OUT / "data" / "watch_ref.png"), full_page=True)
        await b.close()
    save("watch_state.json", get_json("/api/watch/state"))


async def trace(event_id: str):
    async with async_playwright() as p:
        b, pg = await page_for(p)
        await pg.goto(f"{BASE}/trace/{event_id}", wait_until="networkidle")
        await pg.wait_for_selector(".tr-brief", timeout=60000)
        await pg.wait_for_timeout(1500)
        dom = {
            "header": await outer(pg, "header.ph"),
            "rail": await outer(pg, "aside.tr-rail"),
            "out": await outer(pg, "#tr-out"),
        }
        save("trace_dom.json", dom)
        await pg.screenshot(path=str(OUT / "data" / "trace_ref.png"), full_page=True)
        await b.close()
    save("trace.json", get_json(f"/api/trace/{event_id}"))


async def ask():
    q = "What happened at Banjska, and who reported it first?"
    async with async_playwright() as p:
        b, pg = await page_for(p, [{"name": "parse_engine", "value": "retrieval", "url": BASE}])
        await pg.goto(BASE + "/", wait_until="networkidle")
        dom = {"hero": await outer(pg, "section.hero"), "deck": await outer(pg, "section.deck")}
        await pg.fill("#q", q)
        await pg.click("#send")
        await pg.wait_for_selector(".answer h3", timeout=120000)
        await pg.wait_for_timeout(3000)
        dom["turn"] = await outer(pg, "#thread .turn")
        save("ask_dom.json", dom)
        await b.close()


async def chrome():
    async with async_playwright() as p:
        b, pg = await page_for(p)
        await pg.goto(BASE + "/trace", wait_until="networkidle")
        dom = {
            "sprite": await pg.eval_on_selector("body > svg", "e => e.outerHTML"),
            "classbar": await outer(pg, "div.classbar"),
            "nav": await outer(pg, "header.nav"),
            "trace_header": await outer(pg, "header.ph"),
            "trace_why": await outer(pg, "section.tr-why"),
            "trace_input": await outer(pg, "section.tr-input"),
        }
        await pg.goto(BASE + "/how-it-works", wait_until="networkidle")
        dom["rules"] = await pg.evaluate("""() => { const t = [...document.querySelectorAll('table.rules, .rules')];
            return t.length ? t[0].closest('.panel, section, div').outerHTML : ''; }""")
        dom["verdict_panel"] = await pg.evaluate("""() => { const h = [...document.querySelectorAll('h2, .sec')].find(x => /verification verdict/i.test(x.textContent));
            return h ? h.parentElement.outerHTML : ''; }""")
        save("chrome_dom.json", dom)
        await b.close()


def css():
    for f in ["parse.css", "trace.css", "watch.css", "copilot.css", "agents.css"]:
        shutil.copy(STATIC / f, OUT / "product" / f)
        print("copied", f)


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "watch":
        asyncio.run(watch())
    elif what == "trace":
        asyncio.run(trace(sys.argv[2]))
    elif what == "ask":
        asyncio.run(ask())
    elif what == "chrome":
        asyncio.run(chrome())
    elif what == "css":
        css()
