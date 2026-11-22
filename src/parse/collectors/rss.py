"""Live collection from RSS/Atom feeds (A6 news, A8 official). Feeds only hold recent items, so history
comes from backfill.py; this module is the "as if live" poller."""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser
import trafilatura
from sqlalchemy import select

from parse.db import session
from parse.fetch import Fetcher, RobotsDisallowed
from parse.models import Source
from parse.normalise.text import is_kosovo_relevant
from parse.registry import RegistryGateError

from .backfill import _html_to_text
from .emit import already_have, emit, og_image, parse_dt, published_from_html


def poll_source(f: Fetcher, src: Source, fetch_full: bool = True) -> int:
    kept = 0
    for feed_url in src.feed_urls or []:
        if "comments" in feed_url:
            continue
        with session() as s:
            r = f.get(s, feed_url, actor="A6-rss")
        if r.status_code != 200:
            continue
        for e in feedparser.parse(r.content).entries:
            url = e.get("link")
            title = e.get("title")
            summary = _html_to_text(e.get("summary", ""))
            if not url or not is_kosovo_relevant(title, summary, url):
                continue
            with session() as s:
                if already_have(s, src.source_id, url):
                    continue
            published = parse_dt(e.get("published") or e.get("updated"))
            raw, text, ctype, image = r.content, summary, "application/rss+xml", None
            if fetch_full:
                try:
                    with session() as s:
                        ar = f.get(s, url, actor="A6-rss")
                    if ar.status_code == 200:
                        raw, ctype = ar.content, "text/html"
                        text = trafilatura.extract(ar.text, url=url) or summary
                        published = published_from_html(ar.content) or published
                        image = og_image(ar.content)
                except (RegistryGateError, RobotsDisallowed):
                    pass  # article on a host outside the registry: keep the feed entry only
            with session() as s:
                sig = emit(s, s.merge(src), url=url, raw=raw, content_type=ctype, title=title, text=text,
                           published_at=published, agent="A8" if src.platform == "official" else "A6",
                           method="rss", window=None, image_url=image)
            kept += sig is not None
    return kept


def run() -> dict[str, int]:
    with session() as s:
        srcs = list(s.scalars(select(Source).where(Source.mvp_collect == "yes", Source.status == "verified",
                                                   Source.feed_urls.is_not(None))))
    f = Fetcher()
    out = {}
    for src in srcs:
        try:
            out[src.source_id] = poll_source(f, src)
        except Exception as e:
            out[src.source_id] = -1
            print(f"! {src.source_id}: {type(e).__name__}: {e}")
    return out
