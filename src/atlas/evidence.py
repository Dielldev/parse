"""Evidence store: raw HTML + extracted text, content-addressed by SHA-256, written once."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy.orm import Session

from atlas.models import Evidence
from atlas.settings import EVIDENCE_DIR, ROOT


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o444)
    tmp.rename(path)


def archive(s: Session, url: str, raw: bytes, text: str | None, content_type: str | None = None,
            base: Path = EVIDENCE_DIR) -> str:
    """Store raw bytes (and text) under their hash. Returns the SHA-256 of the raw bytes."""
    sha = hashlib.sha256(raw).hexdigest()
    d = base / sha[:2] / sha[2:4]
    html_path = d / f"{sha}.html"
    _write_once(html_path, raw)
    text_path = None
    if text is not None:
        text_path = d / f"{sha}.txt"
        _write_once(text_path, text.encode("utf-8"))
    if s.get(Evidence, sha) is None:
        rel = lambda p: str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
        s.add(Evidence(sha256=sha, url=url, html_uri=rel(html_path),
                       text_uri=rel(text_path) if text_path else None,
                       content_type=content_type, size_bytes=len(raw)))
        s.flush()
    return sha


def verify(path: Path, sha: str) -> bool:
    return hashlib.sha256(path.read_bytes()).hexdigest() == sha
