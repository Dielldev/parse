"""Registry changes made from the Agents page. config/sources.csv stays the source of truth, so each change
is written to the CSV as well as the database (a later `atlas import-sources` keeps it)."""
from __future__ import annotations

import csv
import threading

from atlas.models import AuditLog, Source
from atlas.settings import CONFIG_DIR

from .methods import DISCORD_CHANNEL_RE

CSV_PATH = CONFIG_DIR / "sources.csv"
FIELDS = ["source_id", "platform", "url", "name", "lang", "tier", "status", "mvp_collect", "origin", "bias_note",
          "tier0_scope"]
_lock = threading.Lock()


def _rewrite(update) -> None:
    with _lock:
        rows = list(csv.DictReader(CSV_PATH.open()))
        rows = update(rows)
        with CSV_PATH.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def add_discord_channel(s, url: str, name: str, tier: int, lang: str, note: str = "") -> Source:
    url = url.strip().rstrip("/")
    m = DISCORD_CHANNEL_RE.match(url)
    if not m:
        raise ValueError("Paste a channel link like https://discord.com/channels/123/456 "
                         "(right-click the channel in Discord, then Copy Link).")
    if tier not in (0, 1, 2, 3):
        raise ValueError("Tier must be 0-3.")
    sid = f"src_dc_{m.group(2)}"
    src = s.get(Source, sid) or Source(source_id=sid)
    src.platform, src.url, src.name, src.lang, src.tier = "discord", url, name.strip()[:120] or sid, lang or "en", tier
    src.status, src.mvp_collect, src.origin, src.bias_note = "verified", "yes", "agents-page", note.strip() or None
    src.check_note = "added on the Agents page; read through your own Discord bot"
    s.add(src)
    s.add(AuditLog(actor="agents-page", action="registry_add", allowed=True,
                   detail={"source_id": sid, "url": url, "platform": "discord"}))
    row = {"source_id": sid, "platform": "discord", "url": url, "name": src.name, "lang": src.lang, "tier": tier,
           "status": "verified", "mvp_collect": "yes", "origin": "agents-page", "bias_note": src.bias_note or "",
           "tier0_scope": ""}
    _rewrite(lambda rows: [r for r in rows if r["source_id"] != sid] + [row])
    return src


def approve(s, source_id: str) -> Source:
    """Let agents visit a source the registry had parked (e.g. Telegram channels marked 'later')."""
    src = s.get(Source, source_id)
    if src is None:
        raise ValueError("unknown source")
    if src.mvp_collect.startswith("blocked"):
        raise ValueError(f"{src.name} is {src.mvp_collect}; fix that first, agents cannot work around it.")
    before = (src.status, src.mvp_collect)
    src.status, src.mvp_collect = "verified", "yes"
    s.add(AuditLog(actor="agents-page", action="registry_approve", allowed=True,
                   detail={"source_id": source_id, "before": list(before)}))

    def upd(rows):
        for r in rows:
            if r["source_id"] == source_id:
                r["status"], r["mvp_collect"] = "verified", "yes"
        return rows
    _rewrite(upd)
    return src


def add_scout_source(s, platform: str, sid: str, url: str, name: str) -> Source:
    """A channel the browser scout was sent to that the registry did not know yet. Added as Tier 3 (unverified)."""
    src = Source(source_id=sid, platform=platform, url=url, name=name[:120], lang=None, tier=3, status="verified",
                 mvp_collect="yes", origin="browser-scout", check_note="added when the browser scout was sent here")
    s.add(src)
    s.add(AuditLog(actor="scout", action="registry_add", allowed=True,
                   detail={"source_id": sid, "url": url, "platform": platform}))
    row = {"source_id": sid, "platform": platform, "url": url, "name": src.name, "lang": "", "tier": 3,
           "status": "verified", "mvp_collect": "yes", "origin": "browser-scout", "bias_note": "", "tier0_scope": ""}
    _rewrite(lambda rows: [r for r in rows if r["source_id"] != sid] + [row])
    s.flush()
    return src
