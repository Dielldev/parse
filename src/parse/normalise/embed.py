"""Fill signal.embedding with Qwen/Qwen3-Embedding-0.6B (1024-dim), locally and for free by default.

Multilingual, so an Albanian and a Serbian article about the same incident land close together without
translation. Text = title + lead.
"""
from __future__ import annotations

from sqlalchemy import select

from parse.db import session
from parse.llm import embed_texts
from parse.models import Signal

MAX_CHARS = 2000
BATCH = 64


def run(limit: int | None = None) -> int:
    with session() as s:
        q = select(Signal.signal_id, Signal.title, Signal.text_original).where(Signal.embedding.is_(None))
        rows = s.execute(q.limit(limit) if limit else q).all()
    n = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        vecs = embed_texts(["\n".join(t for t in (title, (text or "")[:MAX_CHARS]) if t) for _, title, text in chunk])
        with session() as s:
            for (sid, _, _), v in zip(chunk, vecs):
                s.get(Signal, sid).embedding = v
        n += len(chunk)
    return n


if __name__ == "__main__":
    print("embedded", run())
