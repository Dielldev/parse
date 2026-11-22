"""Translation to English with Qwen/Qwen3-4B on Featherless (config/models.yaml, role `translation`).

On demand only: detection runs on the original language and Qwen3-Embedding is multilingual, so English is
needed for (a) the "original vs English" classifier comparison and (b) analysts reading alerts. Translating
the whole corpus would spend credits for nothing. Title + lead (MAX_CHARS) only.
Usage:
  uv run python -m parse.normalise.translate estimate --labelled
  uv run python -m parse.normalise.translate run --labelled --approve
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from parse import budget
from parse.db import session
from parse.models import LlmOutput, Signal

ROLE = "translation"
PROMPT_VERSION = "translate-v1"
MAX_CHARS = 1200
SYSTEM = ("Translate the user's text into plain English. Keep names of people, places and organisations as "
          "written, keep quotation marks, add nothing and omit nothing. Output only the translation.")
LANG_NAMES = {"sq": "Albanian", "sr-Latn": "Serbian (Latin script)", "sr-Cyrl": "Serbian (Cyrillic script)",
              "ru": "Russian", "hr": "Croatian", "bs": "Bosnian", "mk": "Macedonian", "bg": "Bulgarian"}


def body(title: str | None, text: str | None) -> str:
    return "\n".join(t for t in (title, (text or "")[:MAX_CHARS]) if t)


def select_ids(labelled: bool, ids: list[str] | None) -> list[tuple]:
    with session() as s:
        q = select(Signal.signal_id, Signal.lang, Signal.title, Signal.text_original).where(Signal.text_en.is_(None))
        if ids:
            q = q.where(Signal.signal_id.in_(ids))
        elif labelled:
            labelled_ids = select(LlmOutput.subject_id).where(LlmOutput.stage == "teacher-label")
            q = q.where(Signal.signal_id.in_(labelled_ids))
        return s.execute(q).all()


def estimate(rows) -> dict:
    tin = sum(len(body(t, x)) / 3.2 + 60 for _, _, t, x in rows)
    tout = sum(len(body(t, x)) / 4.0 for _, _, t, x in rows)
    return {"model": budget.model(ROLE)["id"], "signals": len(rows),
            "usd_developer_plan": round(budget.cost(ROLE, int(tin), int(tout)), 3), "usd_flat_rate_plan": 0.0}


def translate_one(fl, sid, lang, title, text) -> dict:
    """Translate and store one signal. Returns the usage ({"in", "out", "usd"}); English costs nothing."""
    src = body(title, text)
    usage = {"in": 0, "out": 0, "usd": 0.0}
    if lang == "en":
        en = src
    else:
        en, usage = fl.chat_text(ROLE, "translate", SYSTEM,
                                 f"Source language: {LANG_NAMES.get(lang, 'unknown')}\n\n{src}", max_tokens=900)
    with session() as s:
        s.get(Signal, sid).text_en = en.strip()
        s.add(LlmOutput(stage="translate", model=budget.model(ROLE)["id"], prompt_version=PROMPT_VERSION,
                        subject_id=sid, output={"lang": lang}, input_tokens=usage["in"],
                        output_tokens=usage["out"], usd=usage["usd"]))
    return usage


def run(rows, approve: bool) -> int:
    est = estimate(rows)
    budget.check(est["usd_developer_plan"])
    if not approve and budget.require_approval():
        raise SystemExit("Not run: pass --approve after the estimate has been approved.")
    from parse.llm import Featherless
    fl = Featherless()
    with ThreadPoolExecutor(budget.models_cfg()["featherless"]["max_concurrency"]) as ex:
        list(ex.map(lambda r: translate_one(fl, *r), rows))
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["estimate", "run"])
    ap.add_argument("--labelled", action="store_true", help="only signals that have teacher labels")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    rows = select_ids(a.labelled, a.ids)
    print(json.dumps(estimate(rows), indent=2))
    if a.cmd == "run":
        print("translated", run(rows, a.approve))
