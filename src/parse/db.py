"""Database access. Postgres for the pipeline; in demo mode a read-only SQLite snapshot (see scripts/build_demo_db.py)."""
from __future__ import annotations

import gzip
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from parse.settings import DATABASE_URL, DEMO, DEMO_DB, DEMO_DB_GZ


def _demo_db_path() -> Path:
    """The snapshot ships gzipped; unpack it once per process into the temp dir (the deploy bundle is read-only)."""
    if DEMO_DB.exists():
        return DEMO_DB
    out = Path(tempfile.gettempdir()) / "parse_demo.sqlite"
    if not out.exists() or out.stat().st_mtime < DEMO_DB_GZ.stat().st_mtime:
        tmp = out.with_suffix(f".{id(out)}.part")
        with gzip.open(DEMO_DB_GZ, "rb") as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        tmp.replace(out)
    return out


def _fold_regex(pattern: str, value) -> int:
    return 1 if value is not None and re.search(pattern, value, re.IGNORECASE) else 0


def _make_engine():
    if not DEMO:
        return create_engine(DATABASE_URL, pool_pre_ping=True)
    engine = create_engine(f"sqlite:///file:{_demo_db_path()}?mode=ro&uri=true", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi, _rec):   # noqa: ANN001
        dbapi.create_function("parse_regex", 2, _fold_regex, deterministic=True)
        dbapi.execute("PRAGMA query_only = ON")   # belt and braces: the file is opened read-only as well
    return engine


engine = _make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)

if DEMO:
    @event.listens_for(SessionLocal, "before_flush")
    def _discard_writes(sess, _ctx, _instances):   # noqa: ANN001
        """The demo never persists anything a visitor does (labels, translations, traces): drop pending writes
        instead of failing, so code written for the pipeline still runs and returns its result inline."""
        for obj in list(sess.new) + list(sess.dirty) + list(sess.deleted):
            sess.expunge(obj)


@contextmanager
def session() -> Session:
    s = SessionLocal()
    try:
        yield s
        if not DEMO:   # demo: read-only, and closing the session keeps loaded rows usable (a rollback would expire them)
            s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
