"""Screen-recording helpers for the Parse demo videos.

Drives the running Parse web app with Playwright and records it through a CDP screencast
(about 35 fps, native 1920x1080), then writes a timeline (frames + camera moves + captions +
speed-ups) that render.py turns into a finished, zoomed and captioned mp4.

Nothing here talks to the database directly: it only uses the web UI, like a person would.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8765"
W, H = 1920, 1080

CURSOR_JS = r"""
(() => {
  const boot = () => {
    if (document.getElementById('__cur')) return;
    const st = document.createElement('style');
    st.textContent = `
      #__cur{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;width:26px;height:26px;
             margin:-2px 0 0 -2px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.55));will-change:transform}
      .__rip{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;
             border-radius:50%;border:3px solid #ffd33d;background:rgba(255,211,61,.25);
             animation:__rip .55s ease-out forwards}
      @keyframes __rip{to{transform:scale(4.2);opacity:0}}
      html{scroll-behavior:auto!important}`;
    document.documentElement.appendChild(st);
    const c = document.createElement('div'); c.id = '__cur';
    c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.2 18.5 2.7-7.6 7.6-2.7z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    const mv = e => { c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; };
    addEventListener('mousemove', mv, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div'); r.className = '__rip';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700);
    }, true);
  };
  if (document.documentElement) boot(); else addEventListener('DOMContentLoaded', boot);
  addEventListener('DOMContentLoaded', boot);
})();
"""


def ease(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


class Recorder:
    """One clip = one browser session. Use as `async with Recorder('ask', workdir) as r:`."""

    def __init__(self, name: str, workdir: Path, theme: str = "dark"):
        self.name = name
        self.dir = Path(workdir) / name
        self.theme = theme
        self.frames: list[tuple[float, str]] = []
        self.cams: list[dict] = []
        self.caps: list[dict] = []
        self.speeds: list[dict] = []
        self.marks: dict[str, float] = {}
        self.mx, self.my = W * 0.62, H * 0.55
        self._speed_open: dict | None = None

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self):
        if self.dir.exists():
            shutil.rmtree(self.dir)
        (self.dir / "f").mkdir(parents=True)
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(args=["--hide-scrollbars", "--disable-infobars"])
        self.ctx = await self.browser.new_context(
            viewport={"width": W, "height": H}, device_scale_factor=1,
            color_scheme="dark" if self.theme == "dark" else "light", locale="en-US")
        await self.ctx.add_init_script(f"try{{localStorage.setItem('parse-theme','{self.theme}')}}catch(e){{}}")
        await self.ctx.add_init_script(CURSOR_JS)
        self.page = await self.ctx.new_page()
        self.cdp = await self.ctx.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        return self

    def _on_frame(self, ev):
        n = len(self.frames)
        p = self.dir / "f" / f"{n:06d}.jpg"
        p.write_bytes(base64.b64decode(ev["data"]))
        self.frames.append((ev["metadata"]["timestamp"], p.name))
        asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]}))

    async def start(self):
        """Begin capturing. Call once the first page is loaded and ready to be seen."""
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": W, "maxHeight": H,
                                                      "everyNthFrame": 1})
        await asyncio.sleep(0.4)
        self.marks["start"] = time.time()

    async def __aexit__(self, *exc):
        try:
            self.marks["end"] = time.time()
            await asyncio.sleep(0.3)
            await self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        if self._speed_open:
            self.speed_end()
        tl = {"name": self.name, "w": W, "h": H, "frames": self.frames, "cams": self.cams, "caps": self.caps,
              "speeds": self.speeds, "marks": self.marks}
        (self.dir / "timeline.json").write_text(json.dumps(tl))
        await self.browser.close()
        await self._pw.stop()
        print(f"[{self.name}] {len(self.frames)} frames, {self.marks['end'] - self.marks['start']:.1f}s recorded")

    # ------------------------------------------------------------------ navigation
    async def goto(self, path: str, settle: float = 1.0):
        await self.page.goto(BASE + path, wait_until="networkidle")
        await self.page.mouse.move(self.mx, self.my)
        await asyncio.sleep(settle)

    async def hold(self, s: float):
        await asyncio.sleep(s)

    # ------------------------------------------------------------------ human-like input
    async def glide(self, x: float, y: float, dur: float = 0.7):
        steps = max(10, int(dur * 60))
        x0, y0 = self.mx, self.my
        for i in range(1, steps + 1):
            u = ease(i / steps)
            await self.page.mouse.move(x0 + (x - x0) * u, y0 + (y - y0) * u)
            await asyncio.sleep(dur / steps)
        self.mx, self.my = x, y

    async def box(self, sel: str):
        loc = self.page.locator(sel).first
        await loc.wait_for(state="visible", timeout=15000)
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.15)
        b = await loc.bounding_box()
        if not b:
            raise RuntimeError(f"no box for {sel}")
        return b

    async def point_at(self, sel: str, dur: float = 0.7, dx: float = 0.5, dy: float = 0.5):
        b = await self.box(sel)
        await self.glide(b["x"] + b["width"] * dx, b["y"] + b["height"] * dy, dur)
        return b

    async def click(self, sel: str, dur: float = 0.7, pause: float = 0.25, dx: float = 0.5, dy: float = 0.5):
        b = await self.point_at(sel, dur, dx, dy)
        await asyncio.sleep(pause)
        await self.page.mouse.down()
        await asyncio.sleep(0.08)
        await self.page.mouse.up()
        return b

    async def type(self, sel: str, text: str, cps: float = 22):
        await self.click(sel, dur=0.5, pause=0.15)
        for ch in text:
            await self.page.keyboard.type(ch)
            await asyncio.sleep(1 / cps)

    async def scroll(self, dy: float, dur: float = 1.2):
        await self.page.evaluate(
            """([dy, ms]) => new Promise(res => {
                const y0 = scrollY, t0 = performance.now();
                const e = u => u*u*(3-2*u);
                const tick = now => { const u = Math.min(1, (now - t0) / ms); scrollTo(0, y0 + dy * e(u));
                  u < 1 ? requestAnimationFrame(tick) : res(); };
                requestAnimationFrame(tick); })""", [dy, dur * 1000])
        await asyncio.sleep(0.15)

    async def scroll_to(self, sel: str, dur: float = 1.2, offset: float = 120):
        y = await self.page.evaluate(
            "([s, o]) => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().top - o : 0 }", [sel, offset])
        await self.scroll(y, dur)

    # ------------------------------------------------------------------ waiting on the real app
    async def wait_for(self, sel: str, timeout: float = 90, state: str = "visible"):
        await self.page.locator(sel).first.wait_for(state=state, timeout=timeout * 1000)

    # ------------------------------------------------------------------ editing marks (used by render.py)
    def _t(self) -> float:
        return time.time()

    def cam(self, zoom: float = 1.0, cx: float = 0.5, cy: float = 0.5, dur: float = 0.9):
        """Camera move starting now. cx/cy are fractions of the frame (0..1)."""
        self.cams.append({"t": self._t(), "z": zoom, "cx": cx, "cy": cy, "dur": dur})

    async def zoom_on(self, sel: str, zoom: float = 1.5, dur: float = 0.9, dx: float = 0.5, dy: float = 0.5):
        b = await self.box(sel)
        cx = (b["x"] + b["width"] * dx) / W
        cy = (b["y"] + b["height"] * dy) / H
        self.cam(zoom, cx, cy, dur)
        await asyncio.sleep(dur)

    def zoom_out(self, dur: float = 0.9):
        self.cam(1.0, 0.5, 0.5, dur)

    def caption(self, text: str, dur: float = 3.0, sub: str = ""):
        self.caps.append({"t": self._t(), "dur": dur, "text": text, "sub": sub})

    def speed_start(self, factor: float):
        self._speed_open = {"t0": self._t(), "f": factor}

    def speed_end(self):
        s = self._speed_open
        self._speed_open = None
        if s:
            self.speeds.append({"t0": s["t0"], "t1": self._t(), "f": s["f"]})

    @asynccontextmanager
    async def fast(self, factor: float = 4.0):
        self.speed_start(factor)
        try:
            yield
        finally:
            self.speed_end()
