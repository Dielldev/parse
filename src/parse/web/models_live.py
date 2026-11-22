"""Run the Featherless models from the web app: label, detect, translate, check a claim, read an image, write a brief.

Every call is billed and goes through parse.llm.Featherless, which checks the budget cap in config/models.yaml
before the call and records the settled cost to data/spend_ledger.csv. Each result is stored as an LlmOutput row.

The classifier endpoint (detector, nli) is sometimes unavailable on Featherless (503 while the model loads). When
that happens the same question goes to the chat model (role `teacher`), and the result says so.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select

from parse import budget, detect, label_teacher
from parse.db import session
from parse.models import AuditLog, LlmOutput, Signal, Source
from parse.normalise import translate as tr

# What each role in config/models.yaml does, in plain words, and where the web app runs it.
ROLE_INFO = {
    "teacher": {"name": "Threat labeller",
                "does": "Reads a post and tags threat types (T1–T10), narratives (N1–N11), places and organisations. "
                        "Also writes the Ask answer.",
                "where": "Ask: label + brief steps · Signal page: Label"},
    "detector": {"name": "Threat detector",
                 "does": "Gives a probability for every threat type and narrative in one cheap call.",
                 "where": "Signal page: Detect"},
    "nli": {"name": "Claim checker",
            "does": "Says whether an article supports, contradicts or ignores a claim. The verifier uses it.",
            "where": "Signal page: Check a claim"},
    "translation": {"name": "Translator",
                    "does": "Translates Albanian, Serbian and Russian posts into English.",
                    "where": "Ask: translate step · Signal page: Translate"},
    "ocr_fallback": {"name": "Image reader",
                     "does": "Reads the text inside an article's image (captions, leaflets, screenshots).",
                     "where": "Signal page: Read image"},
    "embedding": {"name": "Similarity",
                  "does": "Turns posts into vectors to find near-duplicates and coordinated copies. Free, on this computer.",
                  "where": "Pipeline: embed stage"},
}

WORKERS = 2   # matches featherless.max_concurrency; the client also holds its own semaphore


class ModelError(RuntimeError):
    """A model call failed in a way the page should show as a plain sentence."""


class TooMany(ModelError):
    """This browser started too many model actions in the last minute."""


_recent: dict[str, list[float]] = {}
_recent_lock = __import__("threading").Lock()


def check_rate(who: str) -> None:
    """Per-visitor limit on billed actions started from the web (config featherless.web_actions_per_minute)."""
    limit = int(budget.models_cfg()["featherless"].get("web_actions_per_minute", 10))
    now = time.monotonic()
    with _recent_lock:
        calls = [t for t in _recent.get(who, []) if now - t < 60]
        if len(calls) >= limit:
            wait = int(60 - (now - calls[0])) + 1
            _recent[who] = calls
            raise TooMany(f"Rate limit: {limit} model actions a minute. Try again in {wait}s.")
        calls.append(now)
        _recent[who] = calls


def key_set() -> bool:
    return bool(os.environ.get("FEATHERLESS_API_KEY"))


@lru_cache
def client():
    from parse.llm import Featherless
    return Featherless()   # one client for the whole app so its concurrency limit is shared


def explain(e: Exception) -> str:
    from parse.llm import MissingApiKey
    if isinstance(e, MissingApiKey):
        return "No Featherless key: set FEATHERLESS_API_KEY in .env and restart the server."
    if isinstance(e, budget.BudgetExceeded):
        return f"Budget cap reached: {e}. Raise budget.total_usd in config/models.yaml to keep going."
    if isinstance(e, httpx.HTTPStatusError):
        try:
            msg = e.response.json()["error"]["message"]
        except Exception:
            msg = e.response.text[:200]
        return f"Featherless answered {e.response.status_code}: {msg}"
    if isinstance(e, httpx.TimeoutException):
        return "Featherless did not answer in time."
    return str(e) or type(e).__name__


def _unavailable(e: Exception) -> bool:
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (502, 503, 504)


def _store(stage: str, role: str, prompt_version: str, subject_id: str, output: dict, usage: dict) -> None:
    with session() as s:
        s.add(LlmOutput(stage=stage, model=budget.model(role)["id"], prompt_version=prompt_version,
                        subject_id=subject_id, output=output, input_tokens=usage.get("in"),
                        output_tokens=usage.get("out"), usd=usage.get("usd")))


def _sum(usages: list[dict]) -> dict:
    return {"calls": len(usages), "in": sum(u.get("in", 0) for u in usages),
            "out": sum(u.get("out", 0) for u in usages), "usd": sum(u.get("usd", 0.0) for u in usages)}


# ---------------------------------------------------------------- batch steps used by Ask
def label_many(ids: list[str]) -> dict:
    """Label every signal in `ids` that has no teacher label yet. Returns per-id labels and the total usage."""
    done = set()
    with session() as s:
        done = {x for (x,) in s.execute(select(LlmOutput.subject_id).where(
            LlmOutput.stage == label_teacher.STAGE, LlmOutput.prompt_version == label_teacher.PROMPT_VERSION,
            LlmOutput.subject_id.in_(ids)))}
        todo = s.execute(select(Signal, Source).join(Source).where(
            Signal.signal_id.in_([i for i in ids if i not in done]))).all()
    fl, usages, failed = client(), [], 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for r in ex.map(lambda it: label_teacher.label_one(fl, *it), todo):
            if r:
                usages.append(r["usage"])
            else:
                failed += 1
    with session() as s:
        rows = s.execute(select(Signal.signal_id, Signal.labels, Signal.narratives).where(
            Signal.signal_id.in_(ids))).all()
    return {"labels": {sid: (lab or [], nar or []) for sid, lab, nar in rows}, "new": len(todo) - failed,
            "cached": len(done), "failed": failed, "usage": _sum(usages)}


def translate_many(ids: list[str]) -> dict:
    """Translate the signals in `ids` that are not English and have no English text yet."""
    rows = tr.select_ids(False, ids)
    rows = [r for r in rows if (r[1] or "") != "en"]
    fl = client()
    with ThreadPoolExecutor(WORKERS) as ex:
        usages = list(ex.map(lambda r: tr.translate_one(fl, *r), rows))
    with session() as s:
        en = dict(s.execute(select(Signal.signal_id, Signal.text_en).where(Signal.signal_id.in_(ids))).all())
    return {"en": {k: v for k, v in en.items() if v}, "new": len(rows), "usage": _sum([u for u in usages if u["usd"]])}


class BriefBullet(BaseModel):
    text: str = Field(max_length=400)
    cites: list[int] = []


class Brief(BaseModel):
    headline: str = Field(max_length=300)
    bullets: list[BriefBullet] = Field(max_length=6)


BRIEF_PROMPT = """You are an OSINT analyst writing for the Kosovo Security Force. Answer the user's question using
ONLY the numbered sources and the computed facts below. Never add outside knowledge.
- headline: one sentence that answers the question directly.
- bullets: 3 to 5 findings, each under 40 words, each citing its sources by number in `cites`.
- Say who reported what ("Koha reported…"), not that it is true. Name disagreements between sources.
- If the sources do not answer the question, say so in the headline.
Reply with ONE JSON object and nothing else:
{"headline": "...", "bullets": [{"text": "...", "cites": [1, 2]}]}"""


def write_brief(q: str, cites: list[dict], facts: list[str]) -> tuple[Brief, dict]:
    parts = [f"Question: {q}", "", "Computed facts (from every match, exact):"] + [f"- {f}" for f in facts] + ["", "Sources:"]
    for c in cites:
        body = c.get("en") or c.get("snippet") or ""
        parts.append(f"[{c['n']}] {c['source']} (Tier {c['tier']}, {c['date']}, {c['lang']}): {c['title']}\n    {body[:700]}")
    out, usage = client().chat_json("teacher", "ask-brief", BRIEF_PROMPT, "\n".join(parts), Brief, max_tokens=700)
    return out, usage


# ---------------------------------------------------------------- single-signal actions (Signal page)
class DetectOut(BaseModel):
    probabilities: dict[str, float]


class StanceOut(BaseModel):
    stance: Literal["supports", "contradicts", "unrelated"]
    confidence: float = Field(ge=0, le=1)


def _signal(signal_id: str) -> Signal:
    with session() as s:
        sig = s.get(Signal, signal_id)
    if sig is None:
        raise ModelError("Signal not found.")
    return sig


def run_label(signal_id: str) -> dict:
    with session() as s:
        row = s.execute(select(Signal, Source).join(Source).where(Signal.signal_id == signal_id)).first()
    if row is None:
        raise ModelError("Signal not found.")
    r = label_teacher.label_one(client(), *row)
    if r is None:
        raise ModelError("The model did not return valid labels twice in a row. Try again.")
    lab = r["label"]
    return {"model": budget.model("teacher")["id"], "usage": r["usage"],
            "summary": ("Threat-relevant" if lab.is_threat_relevant else "Not threat-relevant")
                       + (f" · {', '.join(lab.labels + lab.narratives)}" if lab.labels or lab.narratives else "")}


def run_detect(signal_id: str) -> dict:
    sig = _signal(signal_id)
    try:
        probs, usage = detect.detect(client(), sig.title, sig.text_original, tries=1)
        model, note = budget.model("detector")["id"], ""
    except Exception as e:
        if not _unavailable(e):
            raise
        qs = {k: v["instructions"] for k, v in detect.questions().items()}
        system = ("For each question id, give the probability (0.01 to 0.99) that the answer is yes for this post. "
                  "Reply with ONE JSON object: {\"probabilities\": {\"T1\": 0.05, ...}} covering every id.\n\n"
                  + "\n".join(f"{k}: {v}" for k, v in qs.items()))
        out, usage = client().chat_json("teacher", "detect", system, detect.post_text(sig.title, sig.text_original),
                                        DetectOut, max_tokens=500)
        probs = {k: round(min(max(float(v), 0.01), 0.99), 2) for k, v in out.probabilities.items() if k in qs}
        model, note = budget.model("teacher")["id"], "classifier unavailable on Featherless, answered by the chat model"
    _store("detect", "detector" if not note else "teacher", detect.PROMPT_VERSION, signal_id,
           {"probabilities": probs, **({"note": note} if note else {})}, usage)
    top = sorted(probs.items(), key=lambda kv: -kv[1])[:4]
    return {"model": model, "usage": usage, "note": note,
            "summary": ", ".join(f"{k} {v:.2f}" for k, v in top)}


def run_translate(signal_id: str) -> dict:
    sig = _signal(signal_id)
    if sig.lang == "en":
        raise ModelError("This post is already in English.")
    usage = tr.translate_one(client(), sig.signal_id, sig.lang, sig.title, sig.text_original)
    return {"model": budget.model("translation")["id"], "usage": usage, "summary": "English text added below"}


STANCE_SYSTEM = ("Judge ONLY from the evidence text whether it supports or contradicts the claim. Do not use outside "
                 "knowledge. supports = the evidence states or clearly implies the claim is true; contradicts = it "
                 "states or implies the claim is false; unrelated = it does not address the claim. Reply with ONE "
                 'JSON object: {"stance": "supports|contradicts|unrelated", "confidence": 0.0-1.0}')


class _Down(Exception):
    pass


_nli_down_until = 0.0   # the classifier endpoint is often cold on Featherless; skip it for 10 min after a 503


def stance_text(claim: str, evidence: str, subject_id: str | None = None) -> dict:
    """Stance of one evidence text on one claim: the NLI classifier, or the chat model when it is unavailable.

    Stored as an LlmOutput (stage verify-stance). Returns stance, confidence, probabilities, model, usage, note."""
    global _nli_down_until
    try:
        if time.monotonic() < _nli_down_until:   # classifier answered 503 recently: go straight to the chat model
            raise _Down()
        choice, probs, usage = detect.stance(client(), claim, evidence, tries=1)
        model, note = budget.model("nli")["id"], ""
    except Exception as e:
        if not (_unavailable(e) or isinstance(e, _Down)):
            raise
        if not isinstance(e, _Down):
            _nli_down_until = time.monotonic() + 600
        out, usage = client().chat_json("teacher", "verify-stance", STANCE_SYSTEM,
                                        f"CLAIM:\n{claim}\n\nEVIDENCE:\n{evidence[:4000]}", StanceOut, max_tokens=60)
        choice, probs = out.stance, {out.stance: out.confidence}
        model, note = budget.model("teacher")["id"], "classifier unavailable on Featherless, answered by the chat model"
    _store("verify-stance", "nli" if not note else "teacher", "stance-v1", subject_id,
           {"claim": claim, "stance": choice, "probabilities": probs, **({"note": note} if note else {})}, usage)
    return {"stance": choice, "confidence": max(probs.values()) if probs else 0.0, "probabilities": probs,
            "model": model, "usage": usage, "note": note}


def run_claim(signal_id: str, claim: str) -> dict:
    claim = (claim or "").strip()[:500]
    if len(claim) < 5:
        raise ModelError("Write the claim to check first.")
    sig = _signal(signal_id)
    r = stance_text(claim, f"{sig.title or ''}\n\n{sig.text_en or sig.text_original or ''}", subject_id=signal_id)
    return {"model": r["model"], "usage": r["usage"], "note": r["note"],
            "summary": f"{r['stance']} ({r['confidence']:.2f})"}


class TraceBrief(BaseModel):
    text: str = Field(max_length=1400)


TRACE_BRIEF_PROMPT = """You are an OSINT analyst briefing the Kosovo Security Force on how one story spread online.
Write 3 to 5 sentences using ONLY the computed facts and the numbered posts below. Never add outside knowledge.
- Start with what the story is about, in plain words.
- Then where it was first seen and how it travelled. Cite posts as [n].
- Attribution rule: say "earliest observed source", "amplified by" or "consistent with a known network". NEVER write
  that a state, government or leader (Serbia, Russia, Belgrade, Moscow, Kosovo, Albania...) did, ran or is behind it.
- Report what outlets said, not whether it is true; the verdict line in the facts is the only truth statement.
Reply with ONE JSON object and nothing else: {"text": "..."}"""


def write_trace_brief(headline: str, facts: list[str], posts: list[dict]) -> dict:
    parts = ["Headline: " + headline, "", "Computed facts:"] + [f"- {f}" for f in facts] + ["", "Posts:"]
    for p in posts:
        parts.append(f"[{p['n']}] {p['source']} (Tier {p['tier']}, {p['date']}, {p['lang']}, {p['role']}): "
                     f"{p['title']}\n    {p['text']}")
    out, usage = client().chat_json("teacher", "trace-brief", TRACE_BRIEF_PROMPT, "\n".join(parts), TraceBrief,
                                    max_tokens=500)
    _store("trace-brief", "teacher", "trace-brief-v1", None, {"text": out.text}, usage)
    return {"text": out.text, "usage": usage, "model": budget.model("teacher")["id"]}


def run_ocr(signal_id: str) -> dict:
    from parse.fetch import Fetcher
    sig = _signal(signal_id)
    img = next((m for m in (sig.media or []) if m.get("url")), None)
    if img is None:
        raise ModelError("This post has no image to read.")
    url = img["url"]
    f = Fetcher(min_delay=1.0)
    if not f.robots_allows(url):
        raise ModelError("The site's robots.txt does not allow fetching this image.")
    with session() as s:
        s.add(AuditLog(actor="A9-media", action="fetch_media_of_signal", allowed=True,
                       detail={"url": url, "signal_id": signal_id, "origin": "web-ocr"}))
    with session() as s:
        r = f.get(s, url, actor="A9-media", check_registry=False)
    if r.status_code != 200:
        raise ModelError(f"The image could not be downloaded (HTTP {r.status_code}).")
    mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
    text, usage = client().ocr_image("ocr_fallback", "ocr-fallback", r.content, mime)
    _store("ocr-fallback", "ocr_fallback", "ocr-v1", signal_id, {"image": url, "text": text[:4000]}, usage)
    return {"model": budget.model("ocr_fallback")["id"], "usage": usage,
            "summary": (text.strip()[:120] + "…") if len(text.strip()) > 120 else (text.strip() or "No text in the image")}


ACTIONS = {"label": run_label, "detect": run_detect, "translate": run_translate, "ocr": run_ocr}


def run_action(signal_id: str, action: str, claim: str = "") -> dict:
    t0 = time.perf_counter()
    try:
        out = run_claim(signal_id, claim) if action == "claim" else ACTIONS[action](signal_id)
    except ModelError:
        raise
    except Exception as e:
        raise ModelError(explain(e)) from e
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    out["spent_total"] = round(budget.spent(), 4)
    return out
