"""Web-demo hardening (PARSE_DEMO=1, the Vercel deployment).

One pure ASGI middleware, so the same context reaches the streaming responses and their worker threads:

* takes the visitor's own Featherless key from the `X-Featherless-Key` header, holds it in a ContextVar for the
  life of this request only (never stored, never logged, never echoed), and ignores anything that is not key-shaped;
* caps the request body, rejects odd methods, and rate-limits each visitor (best effort: per server instance);
* adds a nonce-based Content-Security-Policy and the other browser security headers to every response.
"""
from __future__ import annotations

import re
import secrets
import threading
import time

from parse.web.models_live import request_key

MAX_BODY = 48_000                       # bytes; the biggest legitimate body is a pasted post (6,000 chars)
KEY_SHAPE = re.compile(r"[A-Za-z0-9._\-]{16,200}")
METHODS = {"GET", "HEAD", "POST"}
PER_MINUTE_ALL = 240                    # any request, per visitor
PER_MINUTE_API_POST = 40                # POST /api/*, per visitor
MODEL_PATHS = re.compile(r"^/api/(trace|key/check|signals/[^/]+/model/[a-z]+)$")

CSP = ("default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline' "
       "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")


class _Limiter:
    def __init__(self):
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, who: str, bucket: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 5000:   # keep memory bounded on a long-lived instance
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 60}
            calls = [t for t in self._hits.get((who, bucket), []) if now - t < 60]
            if len(calls) >= limit:
                self._hits[(who, bucket)] = calls
                return False
            calls.append(now)
            self._hits[(who, bucket)] = calls
            return True


_limiter = _Limiter()


def client_ip(headers: dict[str, str], fallback: str = "?") -> str:
    """Vercel overwrites these headers with the real client address, so they cannot be spoofed by a visitor."""
    return (headers.get("x-real-ip") or headers.get("x-forwarded-for", "").split(",")[0].strip() or fallback)


async def _reply(send, status: int, text: str, extra: list[tuple[bytes, bytes]] | None = None) -> None:
    body = text.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"), *(extra or [])]})
    await send({"type": "http.response.body", "body": body})


class DemoGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method, path = scope["method"], scope["path"]
        who = client_ip(headers, (scope.get("client") or ("?",))[0])

        if method not in METHODS:
            await _reply(send, 405, "Method not allowed", [(b"allow", b"GET, HEAD, POST")])
            return
        if not _limiter.allow(who, "all", PER_MINUTE_ALL) or (
                method == "POST" and path.startswith("/api/") and not _limiter.allow(who, "post", PER_MINUTE_API_POST)):
            await _reply(send, 429, "Too many requests. Wait a minute and try again.", [(b"retry-after", b"60")])
            return
        declared = headers.get("content-length")
        if declared and (not declared.isdigit() or int(declared) > MAX_BODY):
            await _reply(send, 413, "Request too large")
            return

        seen = 0

        async def limited_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > MAX_BODY:   # chunked bodies carry no Content-Length
                    raise RuntimeError("request body too large")
            return msg

        # The visitor's key is only honoured on the routes that call a model, and only when it looks like a key.
        key = headers.get("x-featherless-key", "").strip()
        usable = bool(KEY_SHAPE.fullmatch(key)) and bool(MODEL_PATHS.match(path))
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        is_api = path.startswith("/api/")
        is_static = path.startswith("/static/")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                h = [(k, v) for k, v in message["headers"] if k.lower() not in (b"server", b"x-powered-by")]
                h += [(b"content-security-policy", CSP.format(nonce=nonce).encode()),
                      (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                      (b"referrer-policy", b"no-referrer"),
                      (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
                      (b"cross-origin-opener-policy", b"same-origin"),
                      (b"strict-transport-security", b"max-age=63072000; includeSubDomains")]
                if not is_static:   # pages embed a per-request nonce, and API answers can carry model output
                    h = [(k, v) for k, v in h if k.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]
                elif not any(k.lower() == b"cache-control" for k, _ in h):
                    h.append((b"cache-control", b"public, max-age=3600"))
                message = {**message, "headers": h}
            await send(message)

        token = request_key.set(key if usable else None)
        try:
            await self.app(scope, limited_receive, send_with_headers)
        finally:
            request_key.reset(token)
