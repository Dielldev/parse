"""Polite HTTP fetcher. Enforces: registry gate, robots.txt, per-host rate limit, no logins or cookies."""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from atlas.models import AuditLog
from atlas.registry import gate
from atlas.settings import USER_AGENT

MIN_DELAY_S = 2.0


class RobotsDisallowed(PermissionError):
    pass


class Fetcher:
    def __init__(self, min_delay: float = MIN_DELAY_S, timeout: float = 30.0):
        # No cookie jar persistence and no auth: we never log in (brief s13 "No fake identities").
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout,
                                   follow_redirects=True)
        self.min_delay = min_delay
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.client.get(key + "/robots.txt")
                if r.status_code >= 400:
                    rp = None  # no robots.txt: everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[key] = rp
        return self._robots[key]

    def robots_allows(self, url: str) -> bool:
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        rp = self._robots.get(f"{urlparse(url).scheme}://{host}")
        delay = self.min_delay
        if rp is not None:
            cd = rp.crawl_delay(USER_AGENT)
            if cd:
                delay = max(delay, float(cd))
        with self._lock:
            wait = self._last.get(host, 0) + delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def get(self, s: Session, url: str, actor: str, check_registry: bool = True) -> httpx.Response:
        if check_registry:
            gate(s, url, actor)
        if not self.robots_allows(url):
            s.add(AuditLog(actor=actor, action="robots_block", allowed=False, detail={"url": url}))
            raise RobotsDisallowed(url)
        self._wait(url)
        resp = self.client.get(url)
        if resp.status_code == 429:
            time.sleep(30)
            resp = self.client.get(url)
        return resp
