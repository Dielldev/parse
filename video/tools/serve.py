"""Serve video/src over HTTP on a free local port (the composition fetches its JSON, so file:// will not do)."""
from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 - silence per-request logging
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 256        # several render workers load the page at once


def serve(src: str | Path | None = None) -> tuple[str, socketserver.TCPServer]:
    """Serve `src` (default: video/src, the first film; video/agentic is the agentic-loop film)."""
    handler = functools.partial(_Quiet, directory=str(Path(src).resolve() if src else SRC))
    httpd = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", httpd
