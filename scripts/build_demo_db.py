"""Build the read-only data snapshot behind the public web demo.

    uv run python scripts/build_demo_db.py            # Postgres (DATABASE_URL) -> demo/parse_demo.sqlite.gz

What goes in: the source registry, every signal (text cut to short excerpts that link back to the original),
evidence hashes, the saved traces and alerts, the discovery queue, the recorded model outputs and the
recorded agent runs (the Agents page replays them).
What stays out: embeddings, archived page copies, raw collector internals, personal handles on forum posts, and the
audit log. Nothing in the snapshot is secret; it is the project's own public-source corpus.
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

os.environ.pop("PARSE_DEMO", None)   # build from Postgres, with the Postgres-flavoured engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import create_engine, insert, select  # noqa: E402

from parse import models as m  # noqa: E402
from parse.settings import DATABASE_URL  # noqa: E402

OUT_DIR = ROOT / "demo"
OUT = OUT_DIR / "parse_demo.sqlite"
EXCERPT = 1200          # characters kept of each post; the full text lives at the signal's own URL
BATCH = 2000
TABLES = [m.Source, m.Evidence, m.Signal, m.Event, m.EventSignal, m.EventEdge, m.Alert, m.LlmOutput, m.DiscoveryQueue, m.AgentRun]


def excerpt(text: str | None) -> str | None:
    if not text or len(text) <= EXCERPT:
        return text
    cut = text[:EXCERPT]
    sp = max(cut.rfind(" "), cut.rfind("\n"))
    return (cut[:sp] if sp > EXCERPT * 0.7 else cut).rstrip() + " …"


def fix_signal(row: dict) -> dict:
    row["text_original"] = excerpt(row["text_original"])
    row["text_latin"] = excerpt(row["text_latin"])
    row["text_en"] = excerpt(row["text_en"])
    row["embedding"] = None
    if row["platform"] not in ("telegram", "reddit", "x", "discord"):   # public view/score counts of scouted posts stay
        row["engagement"] = None
    if row["platform"] == "reddit":   # private individuals' handles stay out of a public demo
        row["author_handle"], row["author_followers"], row["author_created_at"] = None, None, None
    return row


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for f in (OUT, OUT.with_suffix(".sqlite-journal")):
        if f.exists():
            f.unlink()
    src = create_engine(DATABASE_URL)
    dst = create_engine(f"sqlite:///{OUT}")
    m.Base.metadata.create_all(dst)   # every table exists (the code reads a few); only the TABLES above get rows

    with src.connect() as s, dst.begin() as d:
        for model in TABLES:
            t = model.__table__
            rows, n = [], 0
            for r in s.execute(select(t)).mappings():
                row = dict(r)
                if model is m.Signal:
                    row = fix_signal(row)
                rows.append(row)
                if len(rows) >= BATCH:
                    d.execute(insert(t), rows)
                    n += len(rows)
                    rows = []
            if rows:
                d.execute(insert(t), rows)
                n += len(rows)
            print(f"{t.name:14s} {n:>7,} rows")

    con = sqlite3.connect(OUT)
    con.execute("ANALYZE")
    con.commit()
    con.execute("VACUUM")
    con.close()

    gz = OUT.with_suffix(".sqlite.gz")
    with OUT.open("rb") as f_in, gz.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as f_out:
        shutil.copyfileobj(f_in, f_out)
    print(f"sqlite {OUT.stat().st_size / 1e6:.1f} MB -> gzip {gz.stat().st_size / 1e6:.1f} MB at {gz.relative_to(ROOT)}")
    assert re.search(r"\.gz$", gz.name)


if __name__ == "__main__":
    main()
