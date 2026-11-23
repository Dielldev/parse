"""Record the Parse feature demos against the running app (default http://127.0.0.1:8765).

  .venv/bin/python video/demo/demo.py ask            # one tab
  .venv/bin/python video/demo/demo.py all            # every tab

Raw frames + timelines go to $PARSE_DEMO_WORK (default: /tmp/parse-demo); finished videos are made by build.py.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import Recorder  # noqa: E402

WORK = Path(os.environ.get("PARSE_DEMO_WORK", "/tmp/parse-demo"))


# --------------------------------------------------------------------------------------------- ASK
async def ask(r: Recorder):
    """~8s: the chatbot. Question -> reasoning (sped up) -> sourced answer -> multilingual citations."""
    await r.goto("/", settle=0.5)
    await r.scroll_to("#suggest", dur=0.01, offset=330)
    await r.hold(0.3)
    await r.start()
    r.caption("Ask Parse: a chatbot over the agents' archive", 3.0, "Every answer shows its steps and sources")
    await r.click('#suggest button[data-q="What happened at Banjska?"]', dur=0.6, pause=0.1)
    await r.wait_for(".turn .cot.running", 10)
    await r.zoom_on(".turn .cot", 1.25, 0.6)
    async with r.fast(9.0):
        await r.wait_for(".turn .cot.done", 120)
    r.zoom_out(0.5)
    await r.wait_for(".turn .answer > *", 20)
    await r.hold(0.4)
    await r.scroll_to(".turn .answer", dur=0.6, offset=110)
    await r.zoom_on(".turn .answer", 1.3, 0.6, dy=0.2)
    await r.hold(1.2)
    r.zoom_out(0.5)
    await r.scroll_to(".turn .cites-h", dur=0.7, offset=250)
    r.caption("Cited items in Albanian, Serbian and English", 2.4)
    await r.zoom_on(".turn .cites", 1.3, 0.6)
    await r.hold(0.7)


# --------------------------------------------------------------------------------------------- TRACE
async def trace(r: Recorder):
    """~8s: paste a claim -> 10 steps (sped up) -> brief -> how it spread."""
    await r.goto("/trace", settle=0.5)
    await r.scroll_to(".tr-examples", dur=0.01, offset=500)
    await r.hold(0.3)
    await r.start()
    r.caption("Tracer: where did a story start, and who carried it?", 3.4, "Paste a post, link or screenshot")
    await r.click(".tr-examples button[data-text^='Shpërthim']", dur=0.6, pause=0.1)
    await r.wait_for(".tr-main:not([hidden])", 10)
    await r.zoom_on(".tr-rail", 1.3, 0.6, dy=0.3)
    async with r.fast(14.0):
        await r.wait_for(".tr-brief", 150)
    r.zoom_out(0.5)
    await r.scroll_to(".tr-brief", dur=0.6, offset=150)
    await r.zoom_on(".tr-brief", 1.25, 0.6, dy=0.3)
    await r.hold(1.2)
    r.zoom_out(0.5)
    await r.scroll_to(".tr-out > :nth-child(3)", dur=0.7, offset=110)
    r.caption("Origin, spread and amplifiers, in any language", 2.6)
    await r.zoom_on(".tr-out > :nth-child(3)", 1.2, 0.6, dx=0.5, dy=0.4)
    await r.hold(0.7)


# --------------------------------------------------------------------------------------------- WATCH
async def watch(r: Recorder):
    """~8s: replay an incident as if live -> pipeline counters -> stories + alert."""
    await r.goto("/watch", settle=0.5)
    await r.scroll_to(".wt-ctl", dur=0.01, offset=110)
    await r.hold(0.3)
    await r.start()
    r.caption("Watch: automatic monitoring that raises alerts", 3.2, "Replaying the Nov 2024 canal blast as if it were live")
    await r.click("#wt-start-btn", dur=0.6, pause=0.1)
    await r.scroll_to(".wt-pipe", dur=0.5, offset=110)
    await r.zoom_on(".wt-main", 1.12, 0.6, dx=0.5, dy=0.15)
    t0 = asyncio.get_event_loop().time()
    async with r.fast(6.0):
        while asyncio.get_event_loop().time() - t0 < 24:
            if "RUNNING" not in await r.page.locator("#wt-status").inner_text():
                break
            await r.hold(0.5)
    r.caption("Stories form, get traced, and P1/P2 raise an alert", 2.2)
    await r.hold(1.8)
    if await r.page.locator("#wt-stop-btn").is_visible():
        await r.click("#wt-stop-btn", dur=0.5, pause=0.05)
    await r.hold(0.4)


# --------------------------------------------------------------------------------------------- SIGNALS
async def signals(r: Recorder):
    await r.goto("/signals", settle=1.2)
    await r.start()
    r.caption("Signals", 3.8, "33,000+ archived posts, searchable in three languages")
    await r.hold(2.4)
    await r.zoom_on("table", 1.25, 1.0, dx=0.5, dy=0.1)
    await r.hold(2.0)
    r.zoom_out(0.9)
    await r.type("form.filters input[name=q]", "Banjska", cps=12)
    await r.hold(0.4)
    r.caption("Filter by text, window, language, source", 3.6, "Every row keeps its evidence hash")
    await r.page.keyboard.press("Enter")
    await r.page.wait_for_load_state("networkidle")
    await r.page.mouse.move(r.mx, r.my)
    await r.hold(1.4)
    await r.zoom_on("table", 1.25, 1.0, dx=0.5, dy=0.1)
    await r.hold(2.4)
    r.zoom_out(0.9)
    await r.click("table tbody tr:nth-child(2) a", dur=1.0)
    await r.page.wait_for_load_state("networkidle")
    await r.hold(1.2)
    r.caption("Open any signal: text, translation, evidence", 4.0, "Original wording, English translation, SHA-256 fingerprint")
    await r.hold(3.6)
    await r.scroll(500, 1.4)
    await r.hold(2.0)


# --------------------------------------------------------------------------------------------- SOURCES
async def sources(r: Recorder):
    await r.goto("/sources", settle=1.2)
    await r.start()
    r.caption("Source registry", 3.8, "Parse only collects from sources it has vetted, with tier and bias notes")
    await r.hold(2.4)
    await r.zoom_on("table", 1.35, 1.0, dx=0.4, dy=0.05)
    await r.hold(3.2)
    await r.scroll(700, 1.6)
    r.caption("Tier 0 official to Tier 3 partisan", 3.8, "Truth is judged from independent tiers, not from popularity")
    await r.hold(3.2)
    r.zoom_out(0.9)
    await r.hold(0.8)


# --------------------------------------------------------------------------------------------- WORKFLOW
async def how(r: Recorder):
    """~8s: how Parse solves the problem: three separate questions, 8-stage pipeline, live scoring."""
    await r.goto("/how-it-works", settle=0.5)
    await r.start()
    r.caption("How Parse solves it", 2.2, "Three separate questions: detection, significance, validation")
    await r.zoom_on(".ph .lead", 1.2, 0.6)
    await r.hold(1.6)
    r.caption("Eight stages, from collection to a human decision", 2.4)
    await r.zoom_on(".steps-row", 1.5, 0.6)
    await r.hold(1.2)
    r.zoom_out(0.4)
    await r.scroll_to("input[type=range]", dur=0.7, offset=380)
    r.caption("Try the Threat Priority Score: priority updates live", 2.2)
    for i in range(2):
        await r.click(f"input[type=range] >> nth={i}", dur=0.4, pause=0.05, dx=0.9 if i % 2 == 0 else 0.15)
        await r.hold(0.25)
    await r.hold(0.5)


# --------------------------------------------------------------------------------------------- OVERVIEW
async def overview(r: Recorder):
    await r.goto("/overview", settle=1.2)
    await r.start()
    r.caption("Overview", 3.8, "What has been collected, labelled and spent so far")
    await r.hold(2.4)
    await r.zoom_on(".cards", 1.4, 1.0)
    await r.hold(3.0)
    r.zoom_out(0.9)
    await r.scroll(900, 1.8)
    r.caption("Back-test windows: Banjska, canal blast, Gazimestan", 4.0, "Plus quiet windows so the model learns what normal looks like")
    await r.hold(3.8)
    await r.scroll(900, 1.8)
    await r.hold(2.4)


# --------------------------------------------------------------------------------------------- AGENTS
async def _agent_tab(r: Recorder, kind: str, title: str, sub: str):
    """~4s: the platform tab of the Agents console."""
    await r.goto("/agents", settle=0.5)
    await r.scroll_to("#console", dur=0.01, offset=200)
    await r.hold(0.3)
    await r.start()
    r.caption(title, 3.4, sub)
    await r.click(f'.sc-tab[data-kind="{kind}"]', dur=0.6, pause=0.1)
    await r.zoom_on("#console", 1.35, 0.6, dy=0.3)
    await r.hold(1.8)


async def agents_x(r: Recorder):
    await _agent_tab(r, "x", "Agents on X", "Search accounts and profiles, read-only")


async def agents_reddit(r: Recorder):
    await _agent_tab(r, "reddit", "Agents on Reddit", "Subreddits and threads, read-only")


async def agents_discord(r: Recorder):
    await _agent_tab(r, "discord", "Agents on Discord", "Reads only the servers the agent account joined")


async def agents_news(r: Recorder):
    await _agent_tab(r, "web", "Agents on news sites", "One agent per site, in parallel, RSS and search APIs")


async def agents_telegram(r: Recorder):
    """Live Telegram scout (public preview pages, read-only). Hits Telegram: only re-record when needed.
    The shipped 4s clip is cut from an earlier recording of this flow."""
    await r.goto("/agents", settle=0.8)
    await r.start()
    chip = '.sc-sugg[data-kind="telegram"] .sc-chip:not(.all) >> nth=1'
    await r.click(chip, dur=0.8, pause=0.1)
    await r.type("#sc-topic", "Banjska", cps=12)
    await r.click('.ag-depth button[data-n="5"]', dur=0.6, pause=0.1)
    if await r.page.locator("#sc-headed").is_checked():
        await r.click(".sc-switch", dur=0.6, pause=0.1)
    await r.click("#sc-send", dur=0.8)
    await r.wait_for("#sc-live:not([hidden])", 15)
    await r.scroll_to("#sc-live", dur=1.0, offset=110)
    r.caption("Agents on Telegram: watch the scout work, live", 3.2, "Public channels, no login, read-only")
    await r.zoom_on(".sc-stage", 1.15, 0.8)
    async with r.fast(3.0):
        t_end = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < t_end:
            if await r.page.locator("#sc-sum:not([hidden])").count():
                break
            await r.hold(0.5)
    if await r.page.locator("#sc-stop").is_enabled():
        await r.click("#sc-stop", dur=0.7)
    await r.hold(0.5)


async def run(name: str):
    async with Recorder(name, WORK) as r:
        await globals()[name](r)


if __name__ == "__main__":
    names = sys.argv[1:] or ["ask"]
    for n in names:
        asyncio.run(run(n))
