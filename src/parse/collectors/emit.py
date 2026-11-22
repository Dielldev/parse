"""Shared Signal emission: archive evidence, normalise, insert (idempotent on source+url)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from dateutil import parser as dtparser
from lxml import html as lxml_html
from sqlalchemy import select
from sqlalchemy.orm import Session

from parse.evidence import archive
from parse.ids import new_id
from parse.models import Signal, Source
from parse.normalise.text import detect_lang, to_latin

COLLECTOR_VERSION = "0.1.0"


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        d = dtparser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def published_from_html(raw: bytes | str) -> datetime | None:
    """Minute-precision publish time from article metadata (needed for lead-time back-tests)."""
    try:
        doc = lxml_html.fromstring(raw)
    except Exception:
        return None
    for xp in ('//meta[@property="article:published_time"]/@content',
               '//meta[@name="article:published_time"]/@content',
               '//meta[@itemprop="datePublished"]/@content',
               '//meta[@name="pubdate"]/@content', '//meta[@name="publish-date"]/@content',
               '//meta[@name="date"]/@content', '//time[@datetime]/@datetime'):
        vals = doc.xpath(xp)
        if vals and (d := parse_dt(vals[0])):
            return d
    for block in doc.xpath('//script[@type="application/ld+json"]/text()'):
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', block)
        if m and (d := parse_dt(m.group(1))):
            return d
    return None


def og_image(raw: bytes | str) -> str | None:
    try:
        v = lxml_html.fromstring(raw).xpath('//meta[@property="og:image"]/@content')
        return v[0] if v else None
    except Exception:
        return None


def already_have(s: Session, source_id: str, url: str) -> bool:
    return s.scalar(select(Signal.signal_id).where(Signal.source_id == source_id, Signal.url == url)) is not None


def emit(s: Session, src: Source, *, url: str, raw: bytes, content_type: str, title: str | None,
         text: str | None, published_at: datetime | None, agent: str, method: str, window: str | None = None,
         links_out: list[str] | None = None, image_url: str | None = None) -> Signal | None:
    if already_have(s, src.source_id, url):
        return None
    sha = archive(s, url, raw, text, content_type)
    body = "\n\n".join(t for t in (title, text) if t)
    lang = detect_lang(body) if body else None
    sig = Signal(
        signal_id=new_id("sig", published_at), platform=src.platform, source_id=src.source_id, url=url,
        published_at=published_at, lang=lang, title=title, text_original=text,
        text_latin=to_latin(body, lang) if lang == "sr-Cyrl" else None,
        media=[{"type": "image", "url": image_url}] if image_url else [],
        links_out=links_out or [], evidence_sha256=sha, window=window, legal_basis="public",
        collector={"agent": agent, "version": COLLECTOR_VERSION, "method": method},
    )
    s.add(sig)
    s.flush()
    return sig


def wp_raw(item: dict) -> bytes:
    return json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
