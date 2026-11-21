"""Image normalisation: download the article's lead image, perceptual hash (pHash), OCR.

OCR: Tesseract locally (free) first; lightonai/LightOnOCR-2-1B on Featherless only as a fallback when a
client is passed in and Tesseract finds almost no text (config/models.yaml, role `ocr_fallback`).

The image belongs to an article from a registry source, but is often served from that outlet's CDN
host. We fetch it without the host gate, still respecting robots.txt and rate limits, and write an
audit record linking it to the signal it came from.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import imagehash
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from atlas.db import session
from atlas.evidence import archive
from atlas.fetch import Fetcher, RobotsDisallowed
from atlas.models import AuditLog, Signal
from atlas.settings import DATA_DIR

TESSDATA = DATA_DIR / "models" / "tessdata"
OCR_LANGS = "sqi+srp+srp_latn+rus+eng"
MAX_BYTES = 8_000_000


def phash(img: Image.Image) -> str:
    return str(imagehash.phash(img))


def phash_distance(a: str, b: str) -> int:
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


def ocr(img: Image.Image) -> str:
    if not shutil.which("tesseract"):
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        img.convert("RGB").save(tmp.name)
        env = {**os.environ, "TESSDATA_PREFIX": str(TESSDATA)}
        r = subprocess.run(["tesseract", tmp.name, "-", "-l", OCR_LANGS], capture_output=True, text=True,
                           env=env, timeout=60)
    return r.stdout.strip()


MIN_TESSERACT_CHARS = 20


def process_signal(f: Fetcher, signal_id: str, do_ocr: bool = True, fl=None) -> bool:
    with session() as s:
        sig = s.get(Signal, signal_id)
        media = list(sig.media or [])
        if not media or media[0].get("phash") or not media[0].get("url"):
            return False
        url = media[0]["url"]
        if not f.robots_allows(url):
            s.add(AuditLog(actor="A9-media", action="robots_block", allowed=False, detail={"url": url}))
            return False
        s.add(AuditLog(actor="A9-media", action="fetch_media_of_signal", allowed=True,
                       detail={"url": url, "signal_id": signal_id}))
    try:
        with session() as s:
            r = f.get(s, url, actor="A9-media", check_registry=False)
        if r.status_code != 200 or len(r.content) > MAX_BYTES:
            return False
        img = Image.open(io.BytesIO(r.content))
        img.load()
    except (RobotsDisallowed, OSError, Exception):
        return False
    text = ocr(img) if do_ocr else ""
    ocr_engine = "tesseract"
    if do_ocr and fl is not None and len(text) < MIN_TESSERACT_CHARS:
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
        text, _ = fl.ocr_image("ocr_fallback", "ocr-fallback", r.content, mime)
        ocr_engine = "lightonocr-2-1b"
    with session() as s:
        sha = archive(s, url, r.content, None, r.headers.get("content-type"))
        sig = s.get(Signal, signal_id)
        m = dict(sig.media[0])
        m.update({"sha256": sha, "phash": phash(img), "ocr_text": text[:4000], "ocr_engine": ocr_engine})
        sig.media = [m] + list(sig.media[1:])
        flag_modified(sig, "media")
    return True


def run(limit: int | None = None, workers: int = 8, do_ocr: bool = True, ocr_fallback: bool = False) -> int:
    with session() as s:
        q = select(Signal.signal_id).where(Signal.media.op("@>")([{"type": "image"}]))
        ids = [x for (x,) in s.execute(q)]
    ids = ids[:limit] if limit else ids
    f = Fetcher(min_delay=1.0)
    with ThreadPoolExecutor(workers) as ex:
        fl = None
        if ocr_fallback:
            from atlas.llm import Featherless
            fl = Featherless()
        return sum(ex.map(lambda i: process_signal(f, i, do_ocr, fl), ids))
