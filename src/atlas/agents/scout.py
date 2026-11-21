"""Browser scout: one button sends a real Chromium window into a public channel and reads it like a person would.

The scout drives its own browser (Playwright, a persistent profile in data/browser-profile), so you can watch it
on this screen and in the live mirror on the Agents page. It goes to the channel, searches it for your topic,
scrolls, highlights each post as it reads it and archives the ones that match, through the same evidence store
as every other collector.

It only reads. It never posts, replies, reacts, joins a server or follows anyone: those stay human actions.

  telegram  t.me/s/<channel>, the public web preview. No account.
  reddit    www.reddit.com: a subreddit's newest posts and the comment threads under them. No account. Reddit
            blocks hidden browsers and shows a human check on search; the scout stops and hands those to you.
  x         x.com search and profiles. X shows nothing logged out, so log the agent browser in once.
  discord   discord.com/channels/<server>/<channel>. Log in once and join the server yourself; it then reads
            channels that account can already see.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import select

from atlas.db import session
from atlas.ids import new_id
from atlas.models import AgentRun, AuditLog, Source
from atlas.normalise.text import fold, is_kosovo_relevant
from atlas.settings import DATA_DIR, keywords

from .methods import DISCORD_CHANNEL_RE, topic_match

PROFILE_DIR = DATA_DIR / "browser-profile"
ACCOUNTS_FILE = DATA_DIR / "browser-accounts.json"
VIEW = {"width": 1280, "height": 800}
BUDGET_S = 240          # a whole run stops after this
READ_CAP = 120          # posts read per target
THREADS_PER_SUB = 3     # Reddit threads opened per target
COMMENTS_PER_THREAD = 10

PLATFORMS = {
    "telegram": {"name": "Telegram", "login": None, "legal": "public",
                 "hint": "@channel or t.me link (empty: sweep the registry's channels)"},
    "discord": {"name": "Discord", "login": "https://discord.com/login", "legal": "restricted:discord-member",
                "hint": "Channel link: discord.com/channels/…/…"},
    "reddit": {"name": "Reddit", "login": "https://www.reddit.com/login", "legal": "public",
               "hint": "r/subreddit (empty: search all of Reddit)"},
    "x": {"name": "X", "login": "https://x.com/login", "legal": "public",
          "hint": "@handle (empty: search all of X)"},
}

TAG_NAMES = {"ksf_military": "KSF / army", "places_north": "North", "police": "Police", "mobilisation": "Mobilisation",
             "violence_sabotage": "Violence", "political": "Political", "war_persecution_framing": "War / persecution",
             "heritage": "Heritage"}


class Busy(RuntimeError):
    """The agent browser is already open (a run or a login window)."""


class NeedsLogin(RuntimeError):
    pass


class Refused(RuntimeError):
    pass


# ---------------------------------------------------------------- targets
TG_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})/?(?:\?.*)?$|^@?([A-Za-z0-9_]{4,})$")
RD_RE = re.compile(r"^(?:https?://)?(?:www\.|old\.)?reddit\.com/r/([A-Za-z0-9_]+)|^/?r/([A-Za-z0-9_]+)/?$|^([A-Za-z0-9_]{3,21})$")
X_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/?(?:\?.*)?$|^@?([A-Za-z0-9_]{1,15})$")


def parse_target(platform: str, raw: str) -> dict | None:
    """Turn what the user typed into {id, url, label}. None means 'no target' (search the whole platform)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if platform == "telegram":
        m = TG_RE.match(raw)
        if m:
            ch = m.group(1) or m.group(2)
            return {"id": f"src_tg_{ch.lower()}", "url": f"https://t.me/s/{ch}", "label": f"@{ch}", "handle": ch}
    elif platform == "reddit":
        m = RD_RE.match(raw)
        if m:
            sub = next(g for g in m.groups() if g)
            return {"id": f"src_rd_{sub.lower()}", "url": f"https://www.reddit.com/r/{sub}/", "label": f"r/{sub}",
                    "handle": sub}
    elif platform == "x":
        m = X_RE.match(raw)
        if m:
            h = m.group(1) or m.group(2)
            if h.lower() not in ("search", "home", "explore", "i", "login"):
                return {"id": f"src_x_{h.lower()}", "url": f"https://x.com/{h}", "label": f"@{h}", "handle": h}
    elif platform == "discord":
        m = DISCORD_CHANNEL_RE.match(raw.rstrip("/"))
        if m:
            return {"id": f"src_dc_{m.group(2)}", "url": raw.rstrip("/"), "label": f"#{m.group(2)[-6:]}",
                    "handle": m.group(2)}
    raise ValueError({"telegram": "Type a channel like @balkanspectator or a t.me link.",
                      "reddit": "Type a subreddit like r/kosovo.",
                      "x": "Type a handle like @NATO_KFOR.",
                      "discord": "Paste a channel link: right-click the channel in Discord → Copy Link."}[platform])


SEARCH_SOURCES = {
    "reddit": {"id": "src_rd_search", "url": "https://www.reddit.com/search", "label": "Reddit search", "handle": None},
    "x": {"id": "src_x_search", "url": "https://x.com/search", "label": "X search", "handle": None},
}


def _norm(u: str) -> str:
    return re.sub(r"^https?://(www\.|old\.)?", "", (u or "").lower()).replace("/s/", "/").rstrip("/")


def ensure_source(s, platform: str, t: dict) -> Source:
    """The registry row for this target. Unknown targets are added (origin browser-scout) and written to the CSV;
    targets the registry blocks stay blocked."""
    from . import registry_edit
    src = s.get(Source, t["id"]) or next(
        (x for x in s.scalars(select(Source).where(Source.platform == platform)) if x.url and _norm(x.url) == _norm(t["url"])),
        None)
    if src is not None:
        if (src.mvp_collect or "").startswith("blocked"):
            raise Refused(f"{src.name} is {src.mvp_collect} in the registry; the scout will not go there.")
        s.add(AuditLog(actor="scout", action="scout_visit", allowed=True, detail={"source_id": src.source_id, "url": t["url"]}))
        return src
    return registry_edit.add_scout_source(s, platform, t["id"], t["url"], t["label"])


def plan(platform: str, target: str, topic: str) -> list[dict]:
    if platform not in PLATFORMS:
        raise ValueError("unknown platform")
    t = parse_target(platform, target)
    if t:
        return [t]
    if platform == "telegram":
        with session() as s:
            rows = [x for x in s.scalars(select(Source).where(Source.platform == "telegram").order_by(Source.tier))
                    if not (x.mvp_collect or "").startswith("blocked") and x.url]
        out = []
        for x in rows[:5]:
            ch = x.url.rstrip("/").rsplit("/", 1)[-1]
            out.append({"id": x.source_id, "url": f"https://t.me/s/{ch}", "label": f"@{ch}", "handle": ch})
        if not out:
            raise ValueError("No Telegram channels in the registry yet. Type one, like @balkanspectator.")
        return out
    if platform == "discord":
        raise ValueError("Paste a Discord channel link: right-click the channel → Copy Link.")
    if not topic:
        raise ValueError(f"Type a topic to search all of {PLATFORMS[platform]['name']}, or name a "
                         f"{'subreddit' if platform == 'reddit' else 'handle'}.")
    return [dict(SEARCH_SOURCES[platform])]


# ---------------------------------------------------------------- tagging
_tags: list[tuple[str, list[str]]] | None = None


def tags_of(text: str) -> list[str]:
    global _tags
    if _tags is None:
        _tags = [(g, sorted({fold(w) for ws in langs.values() for w in ws}))
                 for g, langs in keywords()["topics"].items()]
    blob = fold(text or "")
    out = []
    for g, words in _tags:
        for w in words:
            if (len(w) <= 4 and re.search(rf"\b{re.escape(w)}\b", blob)) or (len(w) > 4 and w in blob):
                out.append(TAG_NAMES.get(g, g))
                break
    return out


# ---------------------------------------------------------------- accounts (which platforms the agent browser is logged in to)
def accounts() -> dict:
    try:
        return json.loads(ACCOUNTS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _set_account(platform: str, connected: bool) -> None:
    a = accounts()
    a[platform] = {"connected": connected, "at": datetime.now(timezone.utc).strftime("%d %b %H:%M")}
    try:
        ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACCOUNTS_FILE.write_text(json.dumps(a))
    except OSError:
        pass


# ---------------------------------------------------------------- run state
_runs: dict[str, dict] = {}
_lock = threading.Lock()
_browser = threading.Lock()      # one persistent profile = one browser at a time
_state = {"busy": None, "window": None}


def busy() -> str | None:
    return _state["busy"]


def _push(run: dict, ev: dict) -> None:
    with _lock:
        ev["i"] = len(run["events"])
        ev["at"] = round(time.monotonic() - run["t0"], 2)
        run["events"].append(ev)


def get(run_id: str) -> dict | None:
    return _runs.get(run_id)


def events(run_id: str, after: int = 0) -> dict | None:
    run = _runs.get(run_id)
    if run is None:
        return None
    with _lock:
        evs = run["events"][after:]
    return {"run_id": run_id, "status": run["status"], "events": evs, "next": after + len(evs)}


def stop(run_id: str) -> bool:
    run = _runs.get(run_id)
    if run is None:
        return False
    run["stop"] = True
    return True


def wait(run_id: str, timeout: float) -> dict:
    run = _runs[run_id]
    run["done"].wait(timeout)
    return run


def start(platform: str, target: str, topic: str, limit: int = 10, headed: bool = True) -> str:
    from atlas.web.ask import terms_of
    topic = (topic or "").strip()[:200]
    targets = plan(platform, target, topic)
    if not _browser.acquire(blocking=False):
        raise Busy("The agent browser is already open. Wait for it, or close it, then try again.")
    try:
        with session() as s:
            for t in targets:
                t["source_id"] = ensure_source(s, platform, t).source_id
            run_id = new_id("run", datetime.now(timezone.utc))
            s.add(AgentRun(run_id=run_id, kind=platform, topic=topic or None, status="running", origin="scout",
                           source_ids=[t["source_id"] for t in targets]))
    except Exception:
        _browser.release()
        raise
    run = {"run_id": run_id, "platform": platform, "topic": topic, "terms": terms_of(topic) if topic else [],
           "limit": max(1, min(int(limit), 50)), "headed": bool(headed), "targets": targets, "status": "running",
           "events": [], "t0": time.monotonic(), "frame": None, "frame_n": 0, "stop": False, "signal_ids": [],
           "stats": {}, "done": threading.Event(), "url": ""}
    with _lock:
        _runs[run_id] = run
    _state["busy"] = "scout"
    _push(run, {"t": "start", "platform": platform, "topic": topic, "terms": run["terms"], "headed": run["headed"],
                "targets": [{"id": t["source_id"], "label": t["label"], "url": t["url"]} for t in targets]})
    threading.Thread(target=_thread, args=(run,), daemon=True, name=f"scout-{run_id}").start()
    return run_id


def _thread(run: dict) -> None:
    try:
        asyncio.run(_main(run))
    except Exception as e:  # noqa: BLE001 — anything here ends the run, never the web app
        run["status"] = "failed"
        _push(run, {"t": "note", "text": f"browser failed: {type(e).__name__}: {e}"[:300]})
    finally:
        if run["status"] == "running":
            run["status"] = "done"
        _finish(run)
        _state["busy"] = None
        _browser.release()


def _finish(run: dict) -> None:
    try:
        with session() as s:
            row = s.get(AgentRun, run["run_id"])
            row.status, row.stats, row.signal_ids = run["status"], run["stats"], run["signal_ids"]
            row.finished_at = datetime.now(timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    posts = run.get("posts", [])
    tags = Counter(t for p in posts if p["kept"] for t in p["tags"])
    authors = Counter(p["author"] for p in posts if p["kept"] and p.get("author"))
    fwd = Counter(p["forwarded"] for p in posts if p.get("forwarded"))
    _push(run, {"t": "end", "status": run["status"], "read": len(posts), "kept": len(run["signal_ids"]),
                "matched": sum(1 for p in posts if p["matched"]), "tags": tags.most_common(8),
                "authors": authors.most_common(5), "forwarded": fwd.most_common(5)})
    run["done"].set()


# ---------------------------------------------------------------- the browser
OVERLAY_JS = r"""
(() => {
  if (window.__atlasOverlay) return; window.__atlasOverlay = 1;
  const boot = () => {
    if (document.getElementById('__atlas_cursor')) return;
    const st = document.createElement('style');
    st.textContent = `
      #__atlas_cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;opacity:0;
        transition:transform .05s linear,opacity .2s;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
      #__atlas_badge{position:fixed;left:14px;bottom:14px;z-index:2147483647;pointer-events:none;
        font:600 11px/1 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;
        background:#0a1433;color:#fff;padding:9px 12px 9px 10px;border-left:3px solid #d0a650;display:flex;gap:8px;align-items:center}
      #__atlas_badge i{width:7px;height:7px;border-radius:50%;background:#ff5a4f;animation:__atlasp 1.2s infinite}
      @keyframes __atlasp{50%{opacity:.25}}
      .__atlas_reading{outline:2px solid #d0a650 !important;outline-offset:3px !important;
        box-shadow:0 0 0 9999px rgba(10,20,51,.10) !important;position:relative;z-index:2}
      .__atlas_hit{outline:2px solid #4f7dff !important;outline-offset:3px !important}`;
    document.documentElement.appendChild(st);
    const c = document.createElement('div'); c.id = '__atlas_cursor';
    c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2.5l6.8 18.2 2.6-7.4 7.4-2.6z" fill="#d0a650" stroke="#0a1433" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const b = document.createElement('div'); b.id = '__atlas_badge'; b.innerHTML = '<i></i>Atlas agent · read-only';
    document.documentElement.append(c, b);
    addEventListener('mousemove', e => { c.style.opacity = 1; c.style.transform = `translate(${e.clientX - 4}px,${e.clientY - 3}px)`; }, true);
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();
})();
"""

# Each extractor tags the post elements with data-atlas-key (so the scout can scroll to and highlight them)
# and returns plain dicts. `key` de-duplicates across scrolls, `ak` finds the element again.
TAG_JS = "el => el.dataset.atlasKey || (el.dataset.atlasKey = 'a' + (window.__atlasN = (window.__atlasN || 0) + 1))"

EXTRACT = {
    "telegram": """() => { const tag = %s;
      const plain = el => { if (!el) return ''; const c = el.cloneNode(true);
        c.querySelectorAll('br').forEach(b => b.replaceWith('\\n'));
        return c.textContent.replace(/[ \\t]+\\n/g, '\\n').replace(/\\n{3,}/g, '\\n\\n').trim(); };
      return [...document.querySelectorAll('.tgme_widget_message[data-post]')].map(m => {
        const q = s => m.querySelector(s), fw = q('.tgme_widget_message_forwarded_from_name');
        const ph = q('.tgme_widget_message_photo_wrap');
        return {ak: tag(m), key: m.dataset.post, url: 'https://t.me/' + m.dataset.post,
          author: (q('.tgme_widget_message_owner_name') || {}).innerText || document.querySelector('.tgme_channel_info_header_title')?.innerText || null,
          text: plain(q('.tgme_widget_message_text')),
          time: q('.tgme_widget_message_date time')?.getAttribute('datetime') || null,
          views: (q('.tgme_widget_message_views') || {}).innerText || null,
          forwarded: fw ? (fw.getAttribute('href') || fw.innerText) : null,
          image: ph ? (ph.style.backgroundImage || '').replace(/^url\\(["']?|["']?\\)$/g, '') || null : null};
      }).reverse(); }""" % TAG_JS,
    "reddit_list": """() => { const tag = %s;
      const posts = [...document.querySelectorAll('shreddit-post')].map(m => {
        const ch = m.getAttribute('content-href') || '';
        return {ak: tag(m), key: m.getAttribute('id') || m.getAttribute('permalink'), kind: 'post',
          url: new URL(m.getAttribute('permalink') || '', 'https://www.reddit.com').href, title: m.getAttribute('post-title') || '',
          text: (m.querySelector('[slot="text-body"]') || {}).innerText || '', author: m.getAttribute('author'),
          sub: m.getAttribute('subreddit-prefixed-name'), time: m.getAttribute('created-timestamp'),
          score: m.getAttribute('score'), replies: m.getAttribute('comment-count'),
          image: /\\.(jpe?g|png|webp)(\\?|$)/i.test(ch) ? ch : null};
      });
      if (posts.length) return posts;
      // search results render as plain cards
      return [...document.querySelectorAll('a[data-testid="post-title"], a[data-testid="post-title-text"]')].map(a => {
        const card = a.closest('[data-testid="search-post-unit"]') || a.parentElement;
        return {ak: tag(card), key: a.getAttribute('href'), kind: 'post', url: a.href, title: a.innerText.trim(), text: '',
          author: null, sub: (a.getAttribute('href') || '').split('/').slice(1, 3).join('/'),
          time: card.querySelector('faceplate-timeago')?.getAttribute('ts') || null};
      }); }""" % TAG_JS,
    "reddit_thread": """() => { const tag = %s, op = document.querySelector('shreddit-post');
      return {selftext: (op?.querySelector('[slot="text-body"]') || {}).innerText || '',
        comments: [...document.querySelectorAll('shreddit-comment')].slice(0, 60).map(c => {
          const body = c.querySelector(':scope > [slot="comment"]') || c.querySelector('[id$="-comment-rtjson-content"]');
          return {ak: tag(c), key: c.getAttribute('thingid'), kind: 'comment',
            url: new URL(c.getAttribute('permalink') || '', 'https://www.reddit.com').href,
            author: c.getAttribute('author'), sub: op?.getAttribute('subreddit-prefixed-name') || '',
            text: (body || {}).innerText || '', time: c.getAttribute('created'), score: c.getAttribute('score')};
        })}; }""" % TAG_JS,
    "x": """() => { const tag = %s;
      return [...document.querySelectorAll('article[data-testid="tweet"]')].map(a => {
        const t = a.querySelector('time'), link = t?.closest('a')?.href || null;
        const un = (a.querySelector('[data-testid="User-Name"]')?.innerText || '').split('\\n');
        return {ak: tag(a), key: link || a.innerText.slice(0, 120), url: link, name: un[0] || null,
          author: (un.find(x => x.startsWith('@')) || un[0] || null),
          text: (a.querySelector('[data-testid="tweetText"]') || {}).innerText || '',
          time: t?.getAttribute('datetime') || null,
          metrics: a.querySelector('[role="group"]')?.getAttribute('aria-label') || '',
          image: a.querySelector('[data-testid="tweetPhoto"] img')?.src || null};
      }); }""" % TAG_JS,
    "discord": """() => { const tag = %s; let last = null;
      const out = [...document.querySelectorAll('li[id^="chat-messages-"]')].map(li => {
        const id = li.id.split('-').pop();
        const u = li.querySelector('[id^="message-username-"]')?.innerText?.trim();
        if (u) last = u;
        return {ak: tag(li), key: id, url: location.origin + location.pathname.replace(/\\/$/, '') + '/' + id,
          author: u || last, text: (li.querySelector('[id^="message-content-"]') || {}).innerText || '',
          time: li.querySelector('time')?.getAttribute('datetime') || null,
          reactions: [...li.querySelectorAll('[class*="reactionCount"]')].reduce((s, e) => s + (parseInt(e.innerText) || 0), 0),
          image: li.querySelector('[class*="imageWrapper"] img')?.src || null};
      });
      return out.reverse(); }""" % TAG_JS,
}


class Scout:
    """One run's hands and eyes: every action is narrated as an event and shown on the page."""

    def __init__(self, run: dict, page, cdp):
        self.run, self.page, self.cdp = run, page, cdp
        self.deadline = time.monotonic() + BUDGET_S
        self.mouse = (VIEW["width"] / 2, VIEW["height"] / 2)
        run["posts"] = []

    def over(self) -> bool:
        return self.run["stop"] or time.monotonic() > self.deadline

    def step(self, action: str, text: str) -> None:
        self.run["url"] = self.page.url
        _push(self.run, {"t": "step", "action": action, "text": text, "url": self.page.url})

    async def pause(self, s: float = 0.6) -> None:
        await asyncio.sleep(s)

    async def goto(self, url: str, why: str) -> None:
        self.step("goto", why)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.run["url"] = self.page.url
        _push(self.run, {"t": "url", "url": self.page.url})
        await self.pause(1.2)

    async def glide(self, x: float, y: float, steps: int = 14) -> None:
        await self.page.mouse.move(x, y, steps=steps)
        self.mouse = (x, y)

    async def wheel(self, dy: int, x: float | None = None, y: float | None = None) -> None:
        self.step("scroll", "Scrolling up for older posts" if dy < 0 else "Scrolling down for more")
        await self.glide(x or VIEW["width"] * 0.55, y or VIEW["height"] * 0.5)
        for _ in range(8):
            await self.page.mouse.wheel(0, dy / 8)
            await asyncio.sleep(0.06)
        await self.pause(1.3)

    async def type_into(self, selector: str, text: str) -> bool:
        """Click a search box and type like a person. False if the box is not there (caller falls back to a URL)."""
        box = self.page.locator(selector).first
        try:
            if not await box.is_visible(timeout=2500):
                return False
            bb = await box.bounding_box()
            if bb:
                await self.glide(bb["x"] + 20, bb["y"] + bb["height"] / 2)
            await box.click()
            self.step("type", f"Typing “{text}” into the search box")
            await box.fill("")
            await box.type(text, delay=70)
            await self.pause(0.4)
            await box.press("Enter")
            await self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            _push(self.run, {"t": "url", "url": self.page.url})
            await self.pause(1.4)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def extract(self, which: str):
        return await self.page.evaluate(EXTRACT[which])

    async def look_at(self, ak: str, hit: bool = False) -> None:
        loc = self.page.locator(f'[data-atlas-key="{ak}"]').first
        try:
            await loc.evaluate("""el => { document.querySelectorAll('.__atlas_reading').forEach(x => x.classList.remove('__atlas_reading'));
                el.scrollIntoView({block: 'center', behavior: 'smooth'}); el.classList.add('__atlas_reading'); }""")
            await asyncio.sleep(0.3)
            bb = await loc.bounding_box()
            if bb:
                await self.glide(bb["x"] + min(60, bb["width"] / 2), bb["y"] + min(28, bb["height"] / 2), steps=8)
            await asyncio.sleep(0.25)
            if hit:
                await loc.evaluate("el => el.classList.add('__atlas_hit')")
                await asyncio.sleep(0.35)
        except Exception:  # noqa: BLE001 — virtualised lists drop elements; reading goes on
            pass

    async def read(self, t: dict, posts: list[dict], seen: set) -> bool:
        """Read posts one by one. Returns False when this target is finished (limit, cap, time, stop)."""
        for p in posts:
            if p["key"] in seen or not (p.get("text") or p.get("title")):
                continue
            seen.add(p["key"])
            if self.over():
                return False
            matched, tags = self.judge(p)
            await self.look_at(p["ak"], hit=matched)
            self.record(t, p, matched, tags)
            if t["kept"] >= self.run["limit"] or t["read"] >= READ_CAP:
                return False
        return True

    def record(self, t: dict, p: dict, matched: bool, tags: list[str]) -> None:
        from atlas.collectors.emit import emit, parse_dt
        platform = self.run["platform"]
        t["read"] += 1
        sig_id = None
        if matched and p.get("url"):
            url = p["url"]
            raw = json.dumps({k: v for k, v in p.items() if k != "ak"}, ensure_ascii=False, sort_keys=True).encode()
            with session() as s:
                src = s.get(Source, t["source_id"])
                sig = emit(s, src, url=url, raw=raw, content_type="application/json", title=p.get("title") or None,
                           text=p.get("text") or None, published_at=parse_dt(p.get("time")), agent="scout",
                           method=f"browser-{platform}", image_url=p.get("image"))
                if sig is not None:
                    sig.platform = platform
                    sig.legal_basis = PLATFORMS[platform]["legal"]
                    sig.author_handle = (p.get("author") or "")[:120] or None
                    sig.forwarded_from = p.get("forwarded")
                    eng = {k: p[k] for k in ("views", "score", "replies", "reactions", "metrics") if p.get(k)}
                    sig.engagement = eng or None
                    sig.collector = {**(sig.collector or {}), "run_id": self.run["run_id"], "sub": p.get("sub")}
                    sig_id = sig.signal_id
        if sig_id:
            t["kept"] += 1
            self.run["signal_ids"].append(sig_id)
        rec = {"t": "post", "target": t["source_id"], "platform": platform, "kind": p.get("kind") or "post",
               "url": p.get("url"), "author": p.get("author"), "name": p.get("name"), "title": p.get("title"),
               "text": (p.get("text") or "")[:900], "time": p.get("time"), "views": p.get("views"),
               "score": p.get("score"), "replies": p.get("replies"), "reactions": p.get("reactions"),
               "metrics": p.get("metrics"), "sub": p.get("sub"), "forwarded": p.get("forwarded"),
               "image": p.get("image"), "matched": matched, "kept": bool(sig_id), "signal_id": sig_id, "tags": tags}
        self.run["posts"].append(rec)
        _push(self.run, rec)

    # ------------------------------------------------------------ playbooks
    async def telegram(self, t: dict) -> None:
        topic = self.run["topic"]
        await self.goto(t["url"], f"Opening {t['label']} (public web preview)")
        title = await self.page.evaluate("() => document.querySelector('.tgme_channel_info_header_title')?.innerText || null")
        subs = await self.page.evaluate("() => [...document.querySelectorAll('.tgme_channel_info_counter')].map(e => e.innerText).join(' · ')")
        if title:
            _push(self.run, {"t": "target_info", "target": t["source_id"], "title": title, "meta": subs})
        if not await self.page.locator(".tgme_widget_message").count():
            raise RuntimeError("no public posts here (private channel, or the name is wrong)")
        if topic:
            searched = await self.type_into("input.tgme_header_search_form_input, input[name=q]", topic)
            if not searched:
                await self.goto(f"{t['url']}?q={quote(topic)}", f"Searching {t['label']} for “{topic}”")
            if not await self.page.locator(".tgme_widget_message").count():
                self.step("read", "No posts match that search; reading the latest posts instead")
                await self.goto(t["url"], f"Back to {t['label']}")
        seen: set = set()
        for rnd in range(5):
            self.step("read", "Reading posts, newest first" if not rnd else f"Reading older posts (page {rnd + 1})")
            if not await self.read(t, await self.extract("telegram"), seen) or self.over():
                return
            before = len(seen)
            await self.page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
            await self.wheel(-2600)
            if not [p for p in await self.extract("telegram") if p["key"] not in seen] and len(seen) == before:
                return

    async def reddit(self, t: dict) -> None:
        topic, sub = self.run["topic"], t.get("handle")
        if sub:
            # Reddit's search page asks logged-out visitors for a human check, so the scout reads the newest
            # posts of the subreddit and filters them for your topic itself.
            await self.goto(f"https://www.reddit.com/r/{sub}/new/", f"Opening {t['label']}, newest posts first")
        else:
            await self.goto(f"https://www.reddit.com/search/?q={quote(topic)}&type=posts&sort=new",
                            f"Searching Reddit for “{topic}”")
        await self._reddit_wall()
        seen: set = set()
        posts: list[dict] = []
        for rnd in range(3 if sub else 2):
            self.step("read", "Reading the post list" if not rnd else f"Reading further down (screen {rnd + 1})")
            known = {p["key"] for p in posts}
            fresh = [p for p in await self.extract("reddit_list") if p["key"] not in known]
            posts += fresh
            if not await self.read(t, fresh, seen) or self.over() or (rnd and not fresh):
                break
            await self.wheel(2400)
        if not posts:
            raise RuntimeError("no posts found (empty search, or the subreddit is private or banned)")
        terms = self.run["terms"]
        picks = [p for p in posts if not terms or topic_match(terms, p.get("title"), p.get("text"))]
        picks.sort(key=lambda p: -int(p.get("replies") or 0))
        for p in picks[:THREADS_PER_SUB]:
            if self.over() or t["read"] >= READ_CAP or not int(p.get("replies") or 0):
                continue
            await self.goto(p["url"], f"Opening the thread: {(p.get('title') or '')[:70]}")
            await self._reddit_wall()
            await self.wheel(900)
            th = await self.extract("reddit_thread")
            cs = [c for c in th["comments"] if c.get("text") and c["key"] not in seen][:COMMENTS_PER_THREAD]
            self.step("read", f"Reading what people say in the comments ({len(cs)} of {len(th['comments'])})")
            # in a thread on the topic, every comment is part of that conversation
            saved, self.run["terms"] = self.run["terms"], []
            try:
                for c in cs:
                    if self.over() or not await self.read(t, [c], seen):
                        break
            finally:
                self.run["terms"] = saved

    def judge(self, p: dict) -> tuple[bool, list[str]]:
        body = " ".join(x for x in (p.get("title"), p.get("text")) if x)
        if p.get("kind") == "comment" and not self.run["terms"]:
            return True, tags_of(body)     # comments inside a matching thread
        matched = topic_match(self.run["terms"], body) if self.run["terms"] else is_kosovo_relevant(body)
        return matched, tags_of(body)

    async def _reddit_wall(self) -> None:
        body = (await self.page.evaluate("() => document.body?.innerText?.slice(0, 2000) || ''")).lower()
        if "prove your humanity" in body:
            raise NeedsLogin("Reddit wants a human check. Open the agent browser (Reddit tab), complete it yourself "
                             "or log in, then send the scout again.")
        if "blocked by network security" in body or "whoa there, pardner" in body:
            raise NeedsLogin("Reddit blocked the hidden browser. Turn on “Show the browser on this screen”, "
                             "or log the agent browser in to Reddit once.")

    async def x(self, t: dict) -> None:
        topic, h = self.run["topic"], t.get("handle")
        if topic:
            q = topic + (f" from:{h}" if h else "")
            await self.goto(f"https://x.com/search?q={quote(q)}&src=typed_query&f=live", f"Searching X for “{q}”, latest first")
        else:
            await self.goto(f"https://x.com/{h}", f"Opening {t['label']}")
        try:
            await self.page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except Exception:  # noqa: BLE001
            if "/login" in self.page.url or "/i/flow" in self.page.url or await self.page.locator('a[href="/login"]').count():
                raise NeedsLogin("X shows nothing logged out. Log the agent browser in to X once, then try again.")
            raise RuntimeError("no posts appeared (no results, or X is rate-limiting this account)")
        seen: set = set()
        for rnd in range(6):
            self.step("read", "Reading posts" if not rnd else f"Reading more posts (screen {rnd + 1})")
            if not await self.read(t, await self.extract("x"), seen) or self.over():
                return
            await self.wheel(1800)

    async def discord(self, t: dict) -> None:
        await self.goto(t["url"], "Opening the Discord channel")
        try:
            await self.page.wait_for_selector('li[id^="chat-messages-"]', timeout=25000)
        except Exception:  # noqa: BLE001
            if "/login" in self.page.url or await self.page.locator('input[name="email"]').count():
                raise NeedsLogin("Discord needs a login. Log the agent browser in to Discord once, then try again.")
            raise RuntimeError("no messages visible. The agent's account must already be in this server: open the "
                               "agent browser, join it yourself, then send the scout again")
        title = await self.page.title()
        _push(self.run, {"t": "target_info", "target": t["source_id"], "title": title.replace("Discord | ", ""), "meta": ""})
        seen: set = set()
        for rnd in range(6):
            self.step("read", "Reading the newest messages" if not rnd else f"Reading older messages (page {rnd + 1})")
            if not await self.read(t, await self.extract("discord"), seen) or self.over():
                return
            await self.wheel(-1600, VIEW["width"] * 0.6, VIEW["height"] * 0.45)


async def _launch(pw, headed: bool):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = await pw.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=not headed, viewport=VIEW, bypass_csp=True, locale="en-US",
        args=[f"--window-size={VIEW['width']},{VIEW['height'] + 88}", "--window-position=60,40"])
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return ctx, page


async def _main(run: dict) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        _push(run, {"t": "step", "action": "launch", "text": "Opening the agent browser" +
                    (" on this screen" if run["headed"] else " (hidden)"), "url": ""})
        ctx, page = await _launch(pw, run["headed"])
        await ctx.add_init_script(OVERLAY_JS)
        cdp = await ctx.new_cdp_session(page)

        async def ack(sid):
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": sid})
            except Exception:  # noqa: BLE001
                pass

        def on_frame(p):
            import base64
            run["frame"] = base64.b64decode(p["data"])
            run["frame_n"] += 1
            asyncio.ensure_future(ack(p["sessionId"]))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 62, "maxWidth": VIEW["width"],
                                                "maxHeight": VIEW["height"], "everyNthFrame": 1})
        if run["headed"]:
            await page.bring_to_front()
        sc = Scout(run, page, cdp)
        platform = run["platform"]
        try:
            for t in run["targets"]:
                t["read"] = t["kept"] = 0
                if sc.over():
                    run["stats"][t["source_id"]] = {"state": "skipped", "note": "stopped" if run["stop"] else "out of time"}
                    _push(run, {"t": "target", "target": t["source_id"], **run["stats"][t["source_id"]]})
                    continue
                _push(run, {"t": "target", "target": t["source_id"], "state": "visiting", "label": t["label"]})
                out = {"state": "done"}
                try:
                    await getattr(sc, platform)(t)
                    out["note"] = f"{t['kept']} kept of {t['read']} read"
                    if PLATFORMS[platform]["login"] and t["read"]:
                        _set_account(platform, True)
                except NeedsLogin as e:
                    out = {"state": "login", "note": str(e)}
                    _set_account(platform, False)
                except Exception as e:  # noqa: BLE001 — one target failing never stops the others
                    out = {"state": "error", "note": (str(e).split("\n")[0] or type(e).__name__)[:300]}
                out.update(read=t["read"], kept=t["kept"])
                run["stats"][t["source_id"]] = out
                _push(run, {"t": "target", "target": t["source_id"], **out})
            if run["stop"]:
                run["status"] = "stopped"
            sc.step("done", "Finished. Closing the browser")
            await asyncio.sleep(1.2)
        finally:
            try:
                await cdp.send("Page.stopScreencast")
            except Exception:  # noqa: BLE001
                pass
            await ctx.close()


# ---------------------------------------------------------------- manual browser window (log in, join a server)
HOMES = {"discord": "https://discord.com/login", "x": "https://x.com/login", "reddit": "https://www.reddit.com/login",
         "telegram": "https://t.me/s/balkanspectator"}


def open_window(platform: str) -> None:
    """Open the agent browser for a human: log in, join a server. It stays open until closed here or on screen."""
    if platform not in HOMES:
        raise ValueError("unknown platform")
    if not _browser.acquire(blocking=False):
        raise Busy("The agent browser is already open.")
    _state["busy"], _state["window"] = "window", {"platform": platform, "stop": False}
    threading.Thread(target=_window_thread, args=(_state["window"],), daemon=True, name="scout-window").start()


def close_window() -> bool:
    if _state["window"] is None:
        return False
    _state["window"]["stop"] = True
    return True


def _window_thread(w: dict) -> None:
    try:
        asyncio.run(_window(w))
    except Exception:  # noqa: BLE001
        pass
    finally:
        _state["busy"], _state["window"] = None, None
        _browser.release()


async def _window(w: dict) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        ctx, page = await _launch(pw, True)
        await page.goto(HOMES[w["platform"]], wait_until="domcontentloaded")
        await page.bring_to_front()
        while not w["stop"] and ctx.pages:
            await asyncio.sleep(0.5)
        try:
            if w["platform"] in ("x", "reddit"):
                names = {c["name"] for c in await ctx.cookies()}
                _set_account(w["platform"], ("auth_token" in names) if w["platform"] == "x" else ("reddit_session" in names))
            elif w["platform"] == "discord":
                p = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await p.goto("https://discord.com/channels/@me", wait_until="domcontentloaded")
                await asyncio.sleep(5)
                _set_account("discord", "/login" not in p.url)
        except Exception:  # noqa: BLE001
            pass
        await ctx.close()
