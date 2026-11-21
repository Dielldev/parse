"""Teacher labeling with Qwen/Qwen3-8B on Featherless (config/models.yaml, role `teacher`).

Nothing paid runs without --approve, and the budget cap in config/models.yaml is checked before each call.
Usage:
  uv run python -m atlas.label_teacher estimate --pilot          # free: sample + estimated cost
  uv run python -m atlas.label_teacher run --pilot --approve     # paid: label 50 posts
  uv run python -m atlas.label_teacher run -n 3000 --approve     # paid: the full teacher set
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from atlas import budget
from atlas.db import session
from atlas.models import LlmOutput, Signal, Source
from atlas.settings import ROOT

ROLE = "teacher"
PROMPT_VERSION = "label-v1"
STAGE = "teacher-label"
MAX_TEXT_CHARS = 3000
EST_OUTPUT_TOKENS = 160   # compact JSON with thinking off; the pilot measures the real value
TEMPLATED_TITLE_REPEATS = 3
TARGET_LANGS = {"sq", "sr-Latn", "sr-Cyrl", "ru", "en"}
CHARS_PER_TOKEN = 3.2     # rough for sq/sr text; replaced by measured usage after the pilot

TCode = Literal["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10"]
NCode = Literal["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11"]


class OfflineIntent(BaseModel):
    present: bool
    span: str = Field(max_length=400)


class TeacherLabel(BaseModel):
    is_threat_relevant: bool
    labels: list[TCode]
    narratives: list[NCode]
    offline_intent: OfflineIntent
    places: list[str]
    orgs: list[str]


JSON_INSTRUCTION = (
    "\n\n## Output format\nReply with ONE JSON object and nothing else, exactly these keys:\n"
    '{"is_threat_relevant": bool, "labels": ["T.."], "narratives": ["N.."], '
    '"offline_intent": {"present": bool, "span": "exact text or empty"}, "places": ["..."], "orgs": ["..."]}'
)


def system_prompt() -> str:
    return (ROOT / "prompts" / f"{PROMPT_VERSION}.md").read_text() + JSON_INSTRUCTION


def user_content(sig: Signal, src: Source) -> str:
    text = (sig.text_original or "")[:MAX_TEXT_CHARS]
    return (f"Source: {src.name} (platform: {sig.platform})\nPublished: {sig.published_at:%Y-%m-%d %H:%M} UTC\n"
            f"Language: {sig.lang}\n\nTitle: {sig.title or ''}\n\nText:\n{text}")


def already_labelled() -> set[str]:
    with session() as s:
        return {x for (x,) in s.execute(select(LlmOutput.subject_id).where(
            LlmOutput.stage == STAGE, LlmOutput.prompt_version == PROMPT_VERSION))}


def select_signals(n: int, seed: int = 7) -> list[tuple[Signal, Source]]:
    """Stratified by window x language so every split and language is represented."""
    done = already_labelled()
    with session() as s:
        rows = s.execute(select(Signal, Source).join(Source).where(Signal.window.is_not(None))).all()
    # Templated daily posts ("weather today", "events today") repeat their title; they teach nothing.
    title_count = Counter((sig.title or "").strip().lower() for sig, _ in rows)
    strata = defaultdict(lambda: defaultdict(list))
    for sig, src in rows:
        if sig.signal_id in done or not sig.text_original or len(sig.text_original) < 200:
            continue
        if sig.lang not in TARGET_LANGS:  # brief s1: sq, sr-Latn, sr-Cyrl, ru, en
            continue
        if title_count[(sig.title or "").strip().lower()] >= TEMPLATED_TITLE_REPEATS:
            continue
        strata[(sig.window, sig.lang)][sig.source_id].append((sig, src))
    rng = random.Random(seed)
    for by_src in strata.values():
        for v in by_src.values():
            rng.shuffle(v)
    # Round-robin over strata, and over sources inside each stratum, so high-volume sites don't dominate.
    out, keys, turn = [], sorted(strata), defaultdict(int)
    while len(out) < n and any(any(v) for v in strata.values()):
        for k in keys:
            srcs = sorted(sid for sid, v in strata[k].items() if v)
            if not srcs or len(out) >= n:
                continue
            sid = srcs[turn[k] % len(srcs)]
            turn[k] += 1
            out.append(strata[k][sid].pop())
    return out


def estimate(items: list[tuple[Signal, Source]]) -> dict:
    sys_tok = int(len(system_prompt()) / 3.8)
    user_tok = sum(int(len(user_content(sig, src)) / CHARS_PER_TOKEN) for sig, src in items)
    n = len(items)
    usd = budget.cost(ROLE, sys_tok * n + user_tok, EST_OUTPUT_TOKENS * n)
    return {"model": budget.model(ROLE)["id"], "posts": n, "system_tokens": sys_tok,
            "avg_user_tokens": user_tok // max(n, 1), "est_output_tokens_each": EST_OUTPUT_TOKENS,
            "usd_developer_plan": round(usd, 3), "usd_flat_rate_plan": 0.0,
            "spent_so_far": round(budget.spent(), 4), "budget_cap": budget.total_budget()}


def label_one(fl, sig: Signal, src: Source) -> bool:
    try:
        out, usage = fl.chat_json(ROLE, STAGE, system_prompt(), user_content(sig, src), TeacherLabel)
    except ValueError:
        return False
    with session() as s:
        s.add(LlmOutput(stage=STAGE, model=budget.model(ROLE)["id"], prompt_version=PROMPT_VERSION,
                        subject_id=sig.signal_id, output=out.model_dump(), input_tokens=usage["in"],
                        output_tokens=usage["out"], usd=usage["usd"]))
        row = s.get(Signal, sig.signal_id)
        row.labels, row.narratives = list(out.labels), list(out.narratives)
        row.entities = {"places": out.places, "orgs": out.orgs}
    return True


def run(items, approve: bool) -> dict:
    est = estimate(items)
    budget.check(est["usd_developer_plan"])
    if not approve:
        raise SystemExit("Not run: pass --approve after the estimate has been approved.")
    from atlas.llm import Featherless
    fl = Featherless()
    workers = budget.models_cfg()["featherless"]["max_concurrency"]
    with ThreadPoolExecutor(workers) as ex:
        ok = sum(ex.map(lambda it: label_one(fl, *it), items))
    return {"labelled": ok, "failed": len(items) - ok, "spent_total": round(budget.spent(), 4)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["estimate", "run"])
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("-n", type=int, default=3000)
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    items = select_signals(50 if a.pilot else a.n)
    print(json.dumps(estimate(items), indent=2))
    if a.cmd == "run":
        print(run(items, a.approve))
