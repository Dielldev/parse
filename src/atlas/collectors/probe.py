"""Probe registry sources: liveness, robots.txt, RSS/Atom feeds, sitemaps and a public WordPress REST API.

Only URLs that are already in the registry are probed. A source moves from `to-verify` to `verified`
only if its registered URL answers HTTP 200 and robots.txt allows us to fetch it.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html
from sqlalchemy import select

from atlas.db import session
from atlas.fetch import Fetcher
from atlas.models import AuditLog, Source

FEED_GUESSES = ("/feed/", "/rss", "/rss.xml", "/feed", "/rss/", "/index.xml", "/atom.xml")


def _looks_like_feed(text: str) -> bool:
    head = text[:600].lower()
    return "<rss" in head or "<feed" in head or "<rdf:rdf" in head


def probe_source(f: Fetcher, src: Source) -> dict:
    out = {"source_id": src.source_id, "ok": False, "status": None, "robots_ok": None, "feeds": [],
           "sitemaps": [], "wp_api": False, "note": ""}
    url = src.url
    try:
        out["robots_ok"] = f.robots_allows(url)
        if not out["robots_ok"]:
            out["note"] = "robots.txt disallows homepage"
            return out
        with session() as s:
            r = f.get(s, url, actor="probe", check_registry=False)
        out["status"] = r.status_code
        if r.status_code != 200:
            out["note"] = f"HTTP {r.status_code}"
            return out
        out["ok"] = True
        base = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}"
        # Feeds declared in the page head.
        try:
            doc = lxml_html.fromstring(r.content)
            for link in doc.xpath('//link[@rel="alternate"][contains(@type,"rss") or contains(@type,"atom")]/@href'):
                out["feeds"].append(urljoin(str(r.url), link))
        except Exception:
            pass
        out["wp_api"] = "wp-json" in r.text or "wp-content" in r.text
        if not out["feeds"]:
            for g in FEED_GUESSES:
                u = base + g
                if not f.robots_allows(u):
                    continue
                with session() as s:
                    fr = f.get(s, u, actor="probe", check_registry=False)
                if fr.status_code == 200 and _looks_like_feed(fr.text):
                    out["feeds"].append(str(fr.url))
                    break
        # Sitemaps from robots.txt, else /sitemap.xml.
        rp = f._robots_for(url)
        sm = list(rp.site_maps() or []) if rp else []
        if not sm:
            u = base + "/sitemap.xml"
            with session() as s:
                sr = f.get(s, u, actor="probe", check_registry=False)
            if sr.status_code == 200 and "<urlset" in sr.text[:2000] or "<sitemapindex" in sr.text[:2000]:
                sm.append(u)
        out["sitemaps"] = sm
        if out["wp_api"]:
            u = base + "/wp-json/wp/v2/posts?per_page=1&_fields=id,date_gmt,link"
            if f.robots_allows(u):
                with session() as s:
                    wr = f.get(s, u, actor="probe", check_registry=False)
                out["wp_api"] = wr.status_code == 200 and wr.text.strip().startswith("[")
            else:
                out["wp_api"] = False
    except Exception as e:  # network errors are reported, not hidden
        out["note"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def run() -> list[dict]:
    with session() as s:
        srcs = list(s.scalars(select(Source).where(Source.mvp_collect == "yes", Source.url.is_not(None))))
    f = Fetcher(min_delay=1.0, timeout=20)
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda x: probe_source(f, x), srcs))
    now = datetime.now(timezone.utc)
    with session() as s:
        for res in results:
            src = s.get(Source, res["source_id"])
            src.last_checked_at = now
            src.feed_urls = sorted(set(res["feeds"])) or None
            src.sitemap_urls = sorted(set(res["sitemaps"])) or None
            parts = [f"http={res['status']}", f"robots_ok={res['robots_ok']}", f"wp_api={res['wp_api']}"]
            if res["note"]:
                parts.append(res["note"])
            src.check_note = "; ".join(parts)
            if res["ok"] and res["robots_ok"] and src.status != "verified":
                s.add(AuditLog(actor="probe", action="status_change", allowed=True,
                               detail={"source_id": src.source_id, "from": src.status, "to": "verified"}))
                src.status = "verified"
            elif not res["ok"] and src.status == "verified":
                src.check_note += "; WARNING: registered as verified but probe failed"
    return results


if __name__ == "__main__":
    for r in run():
        flag = "OK " if r["ok"] else "-- "
        print(flag, r["source_id"], r["status"], "robots", r["robots_ok"], "feeds", len(r["feeds"]),
              "sitemaps", len(r["sitemaps"]), "wp", r["wp_api"], r["note"])
