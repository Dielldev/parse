"""Source registry: CSV import and the registry gate (brief s13: collect only from registry sources)."""
from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.models import AuditLog, Source
from atlas.settings import CONFIG_DIR

COLLECTABLE_STATUS = {"verified"}


class RegistryGateError(PermissionError):
    pass


def import_sources(s: Session, path: Path = CONFIG_DIR / "sources.csv") -> int:
    """Upsert every row of the approved registry CSV. Keeps check results already stored."""
    n = 0
    for row in csv.DictReader(path.open()):
        src = s.get(Source, row["source_id"]) or Source(source_id=row["source_id"])
        src.platform = row["platform"]
        src.url = row["url"] or None
        src.name = row["name"]
        src.lang = row["lang"]
        src.tier = int(row["tier"])
        src.bias_note = row["bias_note"] or None
        src.tier0_scope = row["tier0_scope"] or None
        src.mvp_collect = row["mvp_collect"]
        src.origin = row["origin"]
        if src.status is None or src.status not in COLLECTABLE_STATUS:
            src.status = row["status"]
        s.add(src)
        n += 1
    return n


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def match_source(sources: list[Source], url: str) -> Source | None:
    """Longest-prefix match of `url` against registry URLs and their approved feeds/sitemaps."""
    host, path = _host(url), urlparse(url).path or "/"
    best, best_len = None, -1
    for src in sources:
        candidates = [src.url] if src.url else []
        candidates += list(src.feed_urls or []) + list(src.sitemap_urls or [])
        for c in candidates:
            if _host(c) != host:
                continue
            cpath = urlparse(c).path.rstrip("/")
            # A feed URL on a different path still belongs to the same registered host.
            plen = len(cpath) if path.startswith(cpath) else 0
            if plen > best_len:
                best, best_len = src, plen
    return best


def gate(s: Session, url: str, actor: str) -> Source:
    """Return the registry source for `url` or raise. Every decision is written to the audit log."""
    sources = list(s.scalars(select(Source)))
    src = match_source(sources, url)
    reason = None
    if src is None:
        reason = "not in registry"
    elif src.status not in COLLECTABLE_STATUS:
        reason = f"source status is '{src.status}', needs 'verified'"
    elif src.mvp_collect != "yes":
        reason = f"source collection mode is '{src.mvp_collect}'"
    s.add(AuditLog(actor=actor, action="registry_gate", allowed=reason is None,
                   detail={"url": url, "source_id": src.source_id if src else None, "reason": reason}))
    if reason:
        raise RegistryGateError(f"{url}: {reason}")
    return src
