"""How an agent reads one source. Each visit returns (seen, kept) and reports progress through `ctx`.

Every web request goes through atlas.fetch.Fetcher: registry gate, robots.txt and a per-host delay.
Discord is the one exception: it is an authenticated API, so the agent checks the registry gate on the
channel itself and then calls Discord with the bot token from DISCORD_BOT_TOKEN.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote, urlparse

import feedparser
import httpx
import trafilatura
from lxml import html as lxml_html

from atlas.collectors.backfill import _html_to_text, _links
from atlas.collectors.emit import already_have, emit, og_image, parse_dt, published_from_html, wp_raw
from atlas.db import session
from atlas.fetch import Fetcher, RobotsDisallowed
from atlas.models import Signal, Source
from atlas.normalise.text import fold, is_kosovo_relevant
from atlas.registry import RegistryGateError, gate
from atlas.settings import USER_AGENT

DISCORD_API = "https://discord.com/api/v10"
DISCORD_CHANNEL_RE = re.compile(r"^https://(?:www\.|ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/?$")


class NeedsSetup(RuntimeError):
    """The source cannot be visited until the user does something (a token, a registry change)."""


@dataclass
class Ctx:
    run_id: str
    kind: str
    terms: list[str]
    limit: int
    fetcher: Fetcher
    on_item: Callable[[Source, Signal], None]
    on_note: Callable[[Source, str], None]
    fetch_full: bool = True
    stop_at: float | None = None   # monotonic deadline; agents stop early when Ask is waiting on them
    seen: dict = field(default_factory=dict)

    def late(self) -> bool:
        return self.stop_at is not None and time.monotonic() > self.stop_at


def topic_match(terms: list[str], *texts: str | None) -> bool:
    if not terms:
        return True
    blob = fold(" ".join(t for t in texts if t))
    return any(t in blob for t in terms)


def method_for(src: Source) -> str:
    """The way an agent reads this source, in order of preference."""
    if src.platform == "discord":
        return "discord"
    if src.platform == "telegram":
        return "telegram"
    if "wp_api=True" in (src.check_note or ""):
        return "wp-search"
    if src.feed_urls:
        return "rss"
    if src.sitemap_urls:
        return "sitemap"
    return "none"


def _keep(ctx: Ctx, src: Source, sig: Signal | None, method: str) -> bool:
    if sig is None:
        return False
    sig.collector = {**(sig.collector or {}), "run_id": ctx.run_id, "method": method}
    ctx.on_item(src, sig)
    return True


# ---------------------------------------------------------------- WordPress search API
def visit_wp(ctx: Ctx, src: Source) -> tuple[int, int]:
    p = urlparse(src.url)
    base = f"{p.scheme}://{p.netloc}"
    queries = [" ".join(ctx.terms)] if ctx.terms else [""]
    if len(ctx.terms) > 1:
        queries.append(max(ctx.terms, key=len))   # WordPress ANDs words; retry with the most specific one
    seen = kept = 0
    for qtext in queries:
        url = (f"{base}/wp-json/wp/v2/posts?per_page={min(max(ctx.limit * 3, 10), 50)}&orderby=date&order=desc"
               f"&_fields=id,date_gmt,link,title,content" + (f"&search={quote(qtext)}" if qtext else ""))
        ctx.on_note(src, f"GET {url.split('?')[0]}?search={qtext or '(latest)'}")
        with session() as s:
            r = ctx.fetcher.get(s, url, actor=f"agent-{ctx.kind}")
        if r.status_code != 200 or not r.text.lstrip().startswith("["):
            raise RuntimeError(f"WordPress API answered HTTP {r.status_code}")
        items = r.json()
        for it in items:
            seen += 1
            title = _html_to_text(it.get("title", {}).get("rendered", ""))
            content_html = it.get("content", {}).get("rendered", "")
            text = _html_to_text(content_html)
            if not is_kosovo_relevant(title, text):
                continue
            with session() as s:
                sig = emit(s, s.merge(src), url=it["link"], raw=wp_raw(it), content_type="application/json",
                           title=title, text=text, published_at=parse_dt((it.get("date_gmt") or "") + "Z"),
                           agent=f"agent-{ctx.kind}", method="wp-search", links_out=_links(content_html))
                kept += _keep(ctx, src, sig, "wp-search")
            if kept >= ctx.limit or ctx.late():
                return seen, kept
        if items:
            break
    return seen, kept


# ---------------------------------------------------------------- RSS feed
def visit_rss(ctx: Ctx, src: Source) -> tuple[int, int]:
    seen = kept = 0
    for feed_url in src.feed_urls or []:
        if "comments" in feed_url:
            continue
        ctx.on_note(src, f"GET {feed_url}")
        with session() as s:
            r = ctx.fetcher.get(s, feed_url, actor=f"agent-{ctx.kind}")
        if r.status_code != 200:
            ctx.on_note(src, f"feed answered HTTP {r.status_code}")
            continue
        for e in feedparser.parse(r.content).entries:
            seen += 1
            url, title = e.get("link"), e.get("title")
            summary = _html_to_text(e.get("summary", ""))
            if not url or not is_kosovo_relevant(title, summary, url) or not topic_match(ctx.terms, title, summary, url):
                continue
            with session() as s:
                if already_have(s, src.source_id, url):
                    continue
            raw, text, ctype, image = r.content, summary, "application/rss+xml", None
            published = parse_dt(e.get("published") or e.get("updated"))
            if ctx.fetch_full and not ctx.late():
                try:
                    ctx.on_note(src, f"opening {url}")
                    with session() as s:
                        ar = ctx.fetcher.get(s, url, actor=f"agent-{ctx.kind}")
                    if ar.status_code == 200:
                        raw, ctype = ar.content, "text/html"
                        text = trafilatura.extract(ar.text, url=url) or summary
                        published = published_from_html(ar.content) or published
                        image = og_image(ar.content)
                except (RegistryGateError, RobotsDisallowed):
                    pass   # article lives outside the registry: keep the feed entry only
            with session() as s:
                sig = emit(s, s.merge(src), url=url, raw=raw, content_type=ctype, title=title, text=text,
                           published_at=published, agent=f"agent-{ctx.kind}", method="rss", image_url=image)
                kept += _keep(ctx, src, sig, "rss")
            if kept >= ctx.limit or ctx.late():
                return seen, kept
        if seen:
            break
    return seen, kept


# ---------------------------------------------------------------- Telegram public preview
def visit_telegram(ctx: Ctx, src: Source) -> tuple[int, int]:
    url = src.url if "/s/" in (src.url or "") else (src.url or "").replace("t.me/", "t.me/s/")
    ctx.on_note(src, f"GET {url}")
    with session() as s:
        r = ctx.fetcher.get(s, url, actor=f"agent-{ctx.kind}")
    if r.status_code != 200:
        raise RuntimeError(f"preview answered HTTP {r.status_code}")
    doc = lxml_html.fromstring(r.content)
    seen = kept = 0
    for m in reversed(doc.xpath('//div[contains(@class,"tgme_widget_message ")][@data-post]')):
        seen += 1
        post = m.get("data-post")
        text = " ".join(t.strip() for t in m.xpath('.//div[contains(@class,"tgme_widget_message_text")]//text()')).strip()
        if not text or not topic_match(ctx.terms, text):
            continue
        when = m.xpath('.//a[contains(@class,"tgme_widget_message_date")]/time/@datetime')
        views = (m.xpath('.//span[contains(@class,"tgme_widget_message_views")]/text()') or [None])[0]
        fwd = (m.xpath('.//a[contains(@class,"tgme_widget_message_forwarded_from_name")]/@href') or [None])[0]
        post_url = f"https://t.me/{post}"
        with session() as s:
            sig = emit(s, s.merge(src), url=post_url, raw=lxml_html.tostring(m), content_type="text/html",
                       title=None, text=text, published_at=parse_dt(when[0]) if when else None,
                       agent=f"agent-{ctx.kind}", method="telegram-preview")
            if sig is not None:
                sig.forwarded_from = fwd
                sig.engagement = {"views": views} if views else None
            kept += _keep(ctx, src, sig, "telegram-preview")
        if kept >= ctx.limit or ctx.late():
            break
    return seen, kept


# ---------------------------------------------------------------- Discord (your own bot)
def discord_token() -> str | None:
    return os.environ.get("DISCORD_BOT_TOKEN") or None


def visit_discord(ctx: Ctx, src: Source) -> tuple[int, int]:
    m = DISCORD_CHANNEL_RE.match(src.url or "")
    if not m:
        raise RuntimeError("source URL is not a discord.com/channels/<server>/<channel> link")
    token = discord_token()
    if not token:
        raise NeedsSetup("Add DISCORD_BOT_TOKEN to .env and restart the web app")
    guild, channel = m.groups()
    with session() as s:
        gate(s, src.url, actor=f"agent-{ctx.kind}")
    ctx.on_note(src, f"GET /channels/{channel}/messages (Bot API)")
    headers = {"Authorization": f"Bot {token}", "User-Agent": f"DiscordBot (local, 0.1) {USER_AGENT}"}
    with httpx.Client(timeout=30, headers=headers) as c:
        r = c.get(f"{DISCORD_API}/channels/{channel}/messages", params={"limit": 100})
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)))
            r = c.get(f"{DISCORD_API}/channels/{channel}/messages", params={"limit": 100})
    if r.status_code == 401:
        raise NeedsSetup("Discord rejected the bot token (401). Copy a fresh one from the Developer Portal")
    if r.status_code == 403:
        raise NeedsSetup("The bot cannot read this channel (403). Invite it to the server and give it "
                         "View Channel + Read Message History, and turn on Message Content Intent")
    if r.status_code == 404:
        raise RuntimeError("Discord says this channel does not exist (404)")
    r.raise_for_status()
    seen = kept = 0
    for msg in reversed(r.json()):
        seen += 1
        text = (msg.get("content") or "").strip()
        embeds = " ".join(filter(None, (e.get("title") or e.get("description") for e in msg.get("embeds", []))))
        body = "\n".join(filter(None, (text, embeds)))
        if not body or not topic_match(ctx.terms, body):
            continue
        url = f"https://discord.com/channels/{guild}/{channel}/{msg['id']}"
        images = [a["url"] for a in msg.get("attachments", []) if (a.get("content_type") or "").startswith("image/")]
        with session() as s:
            sig = emit(s, s.merge(src), url=url, raw=json.dumps(msg, ensure_ascii=False, sort_keys=True).encode(),
                       content_type="application/json", title=None, text=body,
                       published_at=parse_dt(msg.get("timestamp")), agent=f"agent-{ctx.kind}", method="discord-bot",
                       image_url=images[0] if images else None)
            if sig is not None:
                sig.legal_basis = "restricted:discord-bot"   # not public web: only visible to server members
                sig.author_handle = (msg.get("author") or {}).get("username")
                sig.engagement = {"reactions": sum(x.get("count", 0) for x in msg.get("reactions", []))}
            kept += _keep(ctx, src, sig, "discord-bot")
        if kept >= ctx.limit:
            break
    return seen, kept


VISITORS = {"wp-search": visit_wp, "rss": visit_rss, "telegram": visit_telegram, "discord": visit_discord}
