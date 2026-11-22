"""Historical backfill for news, official and mirror sources.

Strategy per source, in order:
  1. WordPress REST API (/wp-json/wp/v2/posts with after/before): exact timestamps, full text, one request
     per 100 posts. Public and unauthenticated.
  2. Sitemaps: pick child sitemaps and URLs whose date (lastmod or a date in the URL) falls in the window,
     keep URLs whose slug looks Kosovo-relevant, then fetch each article and extract text + publish time.
Every request passes the registry gate, robots.txt and the per-host rate limit (parse.fetch).
"""
from __future__ import annotations

import argparse
import gzip
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

import trafilatura
import yaml
from lxml import etree
from lxml import html as lxml_html
from sqlalchemy import select

from parse.db import session
from parse.fetch import Fetcher, RobotsDisallowed
from parse.models import Source
from parse.normalise.text import fold, is_kosovo_relevant
from parse.registry import RegistryGateError
from parse.settings import CONFIG_DIR

from .emit import already_have, emit, og_image, parse_dt, published_from_html, wp_raw

MAX_FETCH_PER_WINDOW = 250
MAX_KEEP_PER_WINDOW = 300
MAX_WP_PAGES = 30
MAX_SITEMAP_FETCHES = 150

SLUG_STEMS = tuple(fold(x) for x in (
    "kosov", "kurti", "pristin", "prishtin", "kfor", "mitrovic", "zvecan", "zvecan", "jarinj", "banjsk",
    "gazimestan", "gazivod", "ibar", "iber", "srpska-lista", "leposavi", "zubin-potok", "eulex", "unmik",
    "metohij", "kosmet", "gracanic", "rosu", "vidovdan", "serbi", "srbi", "vucic", "polici", "fsk", "ksf",
    "kbs", "ushtri", "vojsk", "veri-", "-veri", "-sever", "sever-", "nato", "barikad", "protest",
    "zgjedhj", "izbor", "kosova", "kosove", "osce", "quint", "kvint", "lajcak", "dijalog", "dialog",
    "kosovo", "косов", "курти", "приштин",
))


@dataclass
class Window:
    name: str
    start: datetime
    end: datetime  # exclusive
    split: str


@dataclass
class Tally:
    source_id: str
    method: str = ""
    per_window: dict = field(default_factory=dict)
    fetched: int = 0
    errors: list = field(default_factory=list)


def load_windows(names: list[str] | None = None) -> list[Window]:
    cfg = yaml.safe_load((CONFIG_DIR / "windows.yaml").read_text())["windows"]
    out = []
    for name, w in cfg.items():
        if names and name not in names:
            continue
        st = datetime.combine(w["start"], datetime.min.time(), timezone.utc)
        en = datetime.combine(w["end"], datetime.min.time(), timezone.utc) + timedelta(days=1)
        out.append(Window(name, st, en, w["split"]))
    return out


def slug_relevant(url: str) -> bool:
    u = fold(unquote(urlparse(url).path))
    return any(s in u for s in SLUG_STEMS)


_DATE_PATTERNS = [
    re.compile(r"(20\d\d)[/_-](\d\d)[/_-](\d\d)"),
    re.compile(r"(20\d\d)(\d\d)(\d\d)"),
]
_MONTH_PATTERNS = [re.compile(r"(20\d\d)[/_-](\d{1,2})(?!\d)")]


def date_hint(url: str) -> tuple[date, date] | None:
    """A date range implied by the URL (day or month), or None."""
    for p in _DATE_PATTERNS:
        m = p.search(url)
        if m:
            try:
                d = date(int(m[1]), int(m[2]), int(m[3]))
                return d, d
            except ValueError:
                pass
    for p in _MONTH_PATTERNS:
        m = p.search(url)
        if m and 1 <= int(m[2]) <= 12:
            y, mo = int(m[1]), int(m[2])
            nxt = date(y + (mo == 12), mo % 12 + 1, 1)
            return date(y, mo, 1), nxt - timedelta(days=1)
    return None


def _overlaps(r: tuple[date, date], w: Window, slack_days: int = 0) -> bool:
    return r[0] <= (w.end + timedelta(days=slack_days)).date() and r[1] >= (w.start - timedelta(days=1)).date()


def _html_to_text(h: str) -> str:
    if not h:
        return ""
    try:
        return lxml_html.fromstring(h).text_content().strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", h).strip()


def _links(h: str) -> list[str]:
    try:
        return [a for a in lxml_html.fromstring(h).xpath("//a/@href") if a.startswith("http")][:50]
    except Exception:
        return []


# ---------------------------------------------------------------- WordPress REST
def backfill_wp(f: Fetcher, src: Source, w: Window, t: Tally) -> int:
    p = urlparse(src.url)
    base = f"{p.scheme}://{p.netloc}"
    kept = 0
    for page in range(1, MAX_WP_PAGES + 1):
        url = (f"{base}/wp-json/wp/v2/posts?after={w.start:%Y-%m-%dT%H:%M:%S}&before={w.end:%Y-%m-%dT%H:%M:%S}"
               f"&per_page=100&page={page}&orderby=date&order=asc"
               f"&_fields=id,date_gmt,link,title,content,excerpt")
        with session() as s:
            r = f.get(s, url, actor="A6-backfill")
        t.fetched += 1
        if r.status_code == 400:  # past the last page
            break
        if r.status_code != 200 or not r.text.lstrip().startswith("["):
            raise RuntimeError(f"wp api HTTP {r.status_code}")
        items = r.json()
        for it in items:
            title = _html_to_text(it.get("title", {}).get("rendered", ""))
            content_html = it.get("content", {}).get("rendered", "")
            text = _html_to_text(content_html)
            published = parse_dt((it.get("date_gmt") or "") + "Z")
            # The API filters on the site's local time; re-check in UTC so window edges are exact.
            if published is None or not (w.start <= published < w.end) or not is_kosovo_relevant(title, text):
                continue
            with session() as s:
                sig = emit(s, s.merge(src), url=it["link"], raw=wp_raw(it), content_type="application/json",
                           title=title, text=text, published_at=published,
                           agent="A6", method="wp-rest", window=w.name, links_out=_links(content_html))
            kept += bool(sig)
            if kept >= MAX_KEEP_PER_WINDOW:
                return kept
        if len(items) < 100:
            break
    return kept


# ---------------------------------------------------------------- Sitemaps
def _parse_sitemap(text: bytes) -> tuple[str, list[tuple[str, datetime | None]]]:
    if text[:2] == b"\x1f\x8b":  # .xml.gz served without Content-Encoding
        text = gzip.decompress(text)
    root = etree.fromstring(text, parser=etree.XMLParser(recover=True, huge_tree=True))
    if root is None:
        return "none", []
    kind = "index" if root.tag.endswith("sitemapindex") else "urlset"
    out = []
    for node in root:
        loc = node.find("{*}loc")
        if loc is None or not (loc.text or "").strip():
            continue
        lm = node.find("{*}lastmod")
        pub = node.find(".//{*}publication_date")  # Google News sitemaps
        d = parse_dt((pub.text if pub is not None else None) or (lm.text if lm is not None else None))
        out.append((loc.text.strip(), d))
    return kind, out


def sitemap_entries(f: Fetcher, src: Source, windows: list[Window], t: Tally) -> list[tuple[str, datetime | None]]:
    """Walk the sitemap tree once per source. Date-named child sitemaps are only opened if they overlap
    one of the windows; undated children are all opened (up to MAX_SITEMAP_FETCHES)."""
    queue = list(src.sitemap_urls or [])
    seen, entries = set(), []
    while queue and len(seen) < MAX_SITEMAP_FETCHES:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            with session() as s:
                r = f.get(s, sm, actor="A6-backfill")
        except (RegistryGateError, RobotsDisallowed) as e:
            t.errors.append(f"sitemap {sm}: {e}")
            continue
        t.fetched += 1
        if r.status_code != 200:
            continue
        kind, items = _parse_sitemap(r.content)
        if kind == "index":
            for loc, lm in items:
                hint = date_hint(loc)
                if hint and not any(_overlaps(hint, w, slack_days=45) for w in windows):
                    continue
                if lm is not None and lm < min(w.start for w in windows) - timedelta(days=1):
                    continue  # child only holds items older than every window
                queue.append(loc)
        else:
            entries.extend(items)
    if queue:
        t.errors.append(f"sitemap walk stopped at {MAX_SITEMAP_FETCHES} files; {len(queue)} not opened")
    return entries


def window_candidates(entries: list[tuple[str, datetime | None]], w: Window) -> list[str]:
    """Relevant-looking URLs for the window, dated inside it first, each group sampled evenly over time
    so the per-window fetch cap does not just keep the first days."""
    inside, near = [], []
    for loc, lm in entries:
        hint = date_hint(loc)
        if hint is not None:
            if not _overlaps(hint, w):
                continue
            d = datetime.combine(hint[0], datetime.min.time(), timezone.utc)
        elif lm is None or not (w.start - timedelta(days=1) <= lm <= w.end + timedelta(days=60)):
            continue  # no date we can trust without fetching the page
        else:
            d = lm
        if slug_relevant(loc):
            (inside if w.start <= d < w.end else near).append((d, loc))
    out = []
    for group in (inside, near):
        group = sorted(dict((loc, d) for d, loc in group).items(), key=lambda kv: kv[1])
        out += [loc for loc, _ in _even_sample(group, MAX_FETCH_PER_WINDOW)]
    return list(dict.fromkeys(out))


def _even_sample(items: list, k: int) -> list:
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def fetch_article(f: Fetcher, src: Source, url: str, w: Window, t: Tally) -> bool:
    with session() as s:
        if already_have(s, src.source_id, url):
            return False
        r = f.get(s, url, actor="A6-backfill")
    t.fetched += 1
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return False
    doc = trafilatura.bare_extraction(r.text, url=url, with_metadata=True, include_comments=False)
    if doc is None:
        return False
    d = doc if isinstance(doc, dict) else doc.as_dict()
    published = published_from_html(r.content) or parse_dt(d.get("date"))
    if published is None or not (w.start <= published < w.end):
        return False
    title, text = d.get("title"), d.get("text")
    if not is_kosovo_relevant(title, text):
        return False
    with session() as s:
        sig = emit(s, s.merge(src), url=url, raw=r.content, content_type="text/html", title=title, text=text,
                   published_at=published, agent="A8" if src.platform == "official" else "A6",
                   method="sitemap+article", window=w.name, image_url=og_image(r.content))
    return sig is not None


def backfill_sitemap(f: Fetcher, src: Source, w: Window, t: Tally, entries) -> int:
    kept = 0
    cands = window_candidates(entries, w)
    for url in cands[:MAX_FETCH_PER_WINDOW]:
        try:
            kept += fetch_article(f, src, url, w, t)
        except (RegistryGateError, RobotsDisallowed) as e:
            t.errors.append(str(e)[:120])
        except Exception as e:
            t.errors.append(f"{url}: {type(e).__name__}")
        if kept >= MAX_KEEP_PER_WINDOW:
            break
    if len(cands) > MAX_FETCH_PER_WINDOW:
        t.errors.append(f"{w.name}: {len(cands)} candidates, capped at {MAX_FETCH_PER_WINDOW}")
    return kept


# ---------------------------------------------------------------- Driver
def backfill_source(f: Fetcher, src: Source, windows: list[Window]) -> Tally:
    t = Tally(src.source_id)
    use_wp = "wp_api=True" in (src.check_note or "")
    entries = None
    for w in windows:
        try:
            if use_wp:
                t.method = "wp-rest"
                try:
                    t.per_window[w.name] = backfill_wp(f, src, w, t)
                    continue
                except (RuntimeError, ValueError) as e:
                    t.errors.append(f"wp failed, falling back to sitemaps: {e}")
                    use_wp = False
            if src.sitemap_urls:
                t.method = "sitemap"
                if entries is None:
                    entries = sitemap_entries(f, src, windows, t)
                t.per_window[w.name] = backfill_sitemap(f, src, w, t, entries)
            else:
                t.method = "none"
                t.per_window[w.name] = 0
        except (RegistryGateError, RobotsDisallowed) as e:
            t.errors.append(f"{w.name}: blocked: {e}")
            t.per_window[w.name] = 0
        except Exception as e:
            t.errors.append(f"{w.name}: {type(e).__name__}: {str(e)[:100]}")
            t.per_window[w.name] = t.per_window.get(w.name, 0)
    return t


def run(source_ids: list[str] | None = None, window_names: list[str] | None = None, workers: int = 24) -> list[Tally]:
    windows = load_windows(window_names)
    with session() as s:
        q = select(Source).where(Source.mvp_collect == "yes", Source.status == "verified",
                                 Source.platform.in_(("news", "official", "mirror")))
        if source_ids:
            q = q.where(Source.source_id.in_(source_ids))
        srcs = list(s.scalars(q))
    f = Fetcher(min_delay=2.0, timeout=30)
    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(backfill_source, f, src, windows): src for src in srcs}
        for fut in as_completed(futs):
            t = fut.result()
            out.append(t)
            print(f"[done] {t.source_id:28s} {t.method:8s} total={sum(t.per_window.values()):4d} "
                  f"fetched={t.fetched:5d} {t.per_window} errors={len(t.errors)}", flush=True)
            for e in t.errors[:5]:
                print(f"        ! {e}", flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="*")
    ap.add_argument("--windows", nargs="*")
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()
    run(a.sources, a.windows, a.workers)
