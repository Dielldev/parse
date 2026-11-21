"""Atlas local web app: see the pipeline's state and try its deterministic logic.

Run:  uv run uvicorn atlas.web.app:app --port 8000   then open http://localhost:8000
Read-only over the database; the scoring and verdict demos call the same code the pipeline uses.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from atlas import budget
from atlas.db import session
from atlas.evidence import verify
from atlas.models import Evidence, LlmOutput, Signal, Source
from atlas.scoring import tps as tps_mod
from atlas.scoring.verdict import EvidenceItem, decide
from atlas.settings import CONFIG_DIR, ROOT, thresholds

HERE = Path(__file__).parent
app = FastAPI(title="Atlas")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

TIER_NAMES = {0: "Official / primary", 1: "Established outlet", 2: "Specialist OSINT", 3: "Partisan or unverified"}
LANGS = ["sq", "sr-Latn", "sr-Cyrl", "ru", "en"]
PAGE_SIZE = 50

# Honest build status, updated by hand as phases land.
PHASES = [
    {"n": 0, "name": "Foundations", "status": "done",
     "what": "Postgres + pgvector, Source/Signal/Event/Alert tables, 103-source registry with tiers, registry gate, "
             "write-once evidence store and audit log."},
    {"n": 1, "name": "Collection and backfill", "status": "in progress",
     "what": "News, official and mirror collectors (WordPress API, sitemaps, RSS), language ID, Cyrillic to Latin, "
             "10 historical windows. Telegram deferred. Translation, OCR and embeddings built, not yet run on the corpus."},
    {"n": 2, "name": "Teacher labels and gold set", "status": "ready, waiting for API key",
     "what": "Qwen3-8B labels posts with T1-T10 / N1-N11; a labeling UI for the team to correct 500-800 posts."},
    {"n": 3, "name": "Classifier and calibration", "status": "not started",
     "what": "Qwen3.5-4B-classifier probabilities, temperature-scaled on the canal window, scored on Gazimestan 2026."},
    {"n": 4, "name": "Clustering and significance", "status": "logic built",
     "what": "Group signals into events with embeddings + image hashes; velocity, independent origins, "
             "coordination, proximity feed the Threat Priority Score."},
    {"n": 5, "name": "Verifier", "status": "logic built",
     "what": "Claim extraction, evidence from Tier 0-1 sources, NLI stance, verdict by fixed rules."},
    {"n": 6, "name": "Alerts, back-test, report", "status": "not started",
     "what": "Brief writer, replay of Gazimestan 2026 for lead time, alert dashboard, REPORT.md, bias report."},
]


def _windows() -> dict:
    return yaml.safe_load((CONFIG_DIR / "windows.yaml").read_text())["windows"]


# ---------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    windows = _windows()
    with session() as s:
        n_sources = s.scalar(select(func.count()).select_from(Source))
        by_status = dict(s.execute(select(Source.mvp_collect, func.count()).group_by(Source.mvp_collect)).all())
        n_signals = s.scalar(select(func.count()).select_from(Signal))
        n_evidence = s.scalar(select(func.count()).select_from(Evidence))
        n_labelled = s.scalar(select(func.count(func.distinct(LlmOutput.subject_id)))
                              .where(LlmOutput.stage == "teacher-label"))
        rows = s.execute(select(Signal.window, Signal.lang, func.count())
                         .where(Signal.window.is_not(None)).group_by(Signal.window, Signal.lang)).all()
        by_tier = dict(s.execute(select(Source.tier, func.count(Signal.signal_id))
                                 .join(Signal, Signal.source_id == Source.source_id).group_by(Source.tier)).all())
    grid = defaultdict(lambda: defaultdict(int))
    for w, lang, n in rows:
        grid[w][lang if lang in LANGS else "other"] += n
    table = [{"name": w, "split": m["split"], "kind": m["kind"], "start": m["start"], "end": m["end"],
              "cells": [grid[w].get(l, 0) for l in LANGS + ["other"]], "total": sum(grid[w].values())}
             for w, m in windows.items()]
    col_totals = [sum(r["cells"][i] for r in table) for i in range(len(LANGS) + 1)]
    return templates.TemplateResponse(request, "overview.html", {
        "phases": PHASES, "n_sources": n_sources, "by_status": by_status, "n_signals": n_signals,
        "n_evidence": n_evidence, "n_labelled": n_labelled, "table": table, "langs": LANGS + ["other"],
        "col_totals": col_totals, "by_tier": by_tier, "tier_names": TIER_NAMES,
        "spent": budget.spent(), "budget_cap": budget.total_budget(),
        "models": budget.models_cfg()["models"]})


@app.get("/sources", response_class=HTMLResponse)
def sources(request: Request, tier: str = "", mode: str = ""):
    with session() as s:
        counts = dict(s.execute(select(Signal.source_id, func.count()).group_by(Signal.source_id)).all())
        q = select(Source).order_by(Source.tier, Source.name)
        if tier != "":
            q = q.where(Source.tier == int(tier))
        if mode:
            q = q.where(Source.mvp_collect.like(f"{mode}%"))
        srcs = list(s.scalars(q))
        modes = sorted({m.split(":")[0] for (m,) in s.execute(select(Source.mvp_collect).distinct())})
    return templates.TemplateResponse(request, "sources.html", {
        "sources": srcs, "counts": counts, "tier_names": TIER_NAMES, "tier": tier, "mode": mode, "modes": modes})


@app.get("/signals", response_class=HTMLResponse)
def signals(request: Request, q: str = "", window: str = "", lang: str = "", source: str = "",
            labelled: str = "", page: int = 1):
    page = max(page, 1)
    with session() as s:
        stmt = select(Signal, Source).join(Source)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Signal.title.ilike(like), Signal.text_original.ilike(like),
                                  Signal.text_latin.ilike(like)))
        if window:
            stmt = stmt.where(Signal.window == window)
        if lang:
            stmt = stmt.where(Signal.lang == lang)
        if source:
            stmt = stmt.where(Signal.source_id == source)
        if labelled == "yes":
            stmt = stmt.where(Signal.labels.is_not(None))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = s.execute(stmt.order_by(Signal.published_at.desc().nulls_last())
                         .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
        src_opts = s.execute(select(Source.source_id, Source.name).join(Signal).distinct()
                             .order_by(Source.name)).all()
    return templates.TemplateResponse(request, "signals.html", {
        "rows": rows, "total": total, "page": page, "pages": max(1, -(-total // PAGE_SIZE)),
        "q": q, "window": window, "lang": lang, "source": source, "labelled": labelled,
        "windows": list(_windows()), "langs": LANGS, "src_opts": src_opts, "tier_names": TIER_NAMES})


@app.get("/signals/{signal_id}", response_class=HTMLResponse)
def signal_detail(request: Request, signal_id: str):
    with session() as s:
        sig = s.get(Signal, signal_id)
        if sig is None:
            raise HTTPException(404, "signal not found")
        src = s.get(Source, sig.source_id)
        ev = s.get(Evidence, sig.evidence_sha256) if sig.evidence_sha256 else None
        llm = list(s.scalars(select(LlmOutput).where(LlmOutput.subject_id == signal_id)
                             .order_by(LlmOutput.created_at)))
    hash_ok = None
    if ev is not None:
        p = ROOT / ev.html_uri
        hash_ok = p.exists() and verify(p, ev.sha256)
    return templates.TemplateResponse(request, "signal.html", {
        "sig": sig, "src": src, "ev": ev, "hash_ok": hash_ok, "llm": llm, "tier_names": TIER_NAMES})


@app.get("/evidence/{sha}/{kind}")
def evidence_file(sha: str, kind: str):
    """Archived content is always served as plain text, so archived pages never run in the browser."""
    if kind not in ("raw", "text") or len(sha) != 64:
        raise HTTPException(404)
    with session() as s:
        ev = s.get(Evidence, sha)
    if ev is None:
        raise HTTPException(404)
    uri = ev.html_uri if kind == "raw" else ev.text_uri
    if not uri or not (ROOT / uri).exists():
        raise HTTPException(404, "file missing from evidence store")
    return PlainTextResponse((ROOT / uri).read_bytes().decode("utf-8", errors="replace"),
                             headers={"X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------- how it works (live logic)
FACTOR_HELP = {
    "severity": "Highest label weight: T2/T3 = 1.0, T1/T8 = 0.8, T4/T5 = 0.7, T6/T7 = 0.6, T9/T10 = 0.4",
    "velocity": "Posts in the last hour against this narrative's own baseline (z-score, capped)",
    "reach": "log10(total followers of posting accounts) / 7",
    "coordination": "Near-duplicates within 10 min, new accounts, fan-out, synchronised headlines",
    "offline_intent": "Probability the posts call for gathering, blocking or attacking",
    "proximity": "1.0 for the north, crossings, infrastructure or a trigger date; 0.5 elsewhere in Kosovo",
}
TRIPWIRES = {
    "t3": "T3 + explosive term + named critical-infrastructure site",
    "t2": "T2 + weapons + place in Kosovo + time reference",
    "n6": "Suspected forged order / deepfake of an official",
    "dox": "Doxxing of KSF or police personnel",
    "t8": "T8 with a named target",
    "rsmod": "Serbian MoD readiness or mobilisation statement",
}


@app.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request):
    return templates.TemplateResponse(request, "how.html", {
        "factors": tps_mod.FACTORS, "factor_help": FACTOR_HELP, "tripwires": TRIPWIRES,
        "weights": thresholds()["tps"]["weights"],
        "tier_names": TIER_NAMES})


@app.post("/api/tps")
async def api_tps(request: Request):
    body = await request.json()
    factors = {k: float(body.get(k, 0)) for k in tps_mod.FACTORS}
    trips = [TRIPWIRES[k] for k in body.get("tripwires", []) if k in TRIPWIRES]
    tier = body.get("best_tier")
    cred = tps_mod.credibility(int(tier) if tier not in (None, "") else None, body.get("verdict") or None)
    r = tps_mod.score(factors, cred, trips)
    return {"tps": r.tps, "priority": r.priority, "credibility": r.credibility, "explanation": r.explanation}


@app.post("/api/verdict")
async def api_verdict(request: Request):
    body = await request.json()
    items = [EvidenceItem(evidence_id=f"e{i + 1}", stance=e["stance"], tier=int(e["tier"]),
                          origin_group=e.get("origin") or f"g{i + 1}", in_tier0_scope=bool(e.get("in_scope")))
             for i, e in enumerate(body.get("evidence", []))]
    v = decide(items, media_recycled_from_unrelated_event=bool(body.get("recycled_media")))
    return {"verdict": v.verdict, "evidence_ids": v.evidence_ids, "reason": v.reason,
            "suggested_checks": v.suggested_checks}


@app.get("/api/stats")
def api_stats():
    with session() as s:
        return {"sources": s.scalar(select(func.count()).select_from(Source)),
                "signals": s.scalar(select(func.count()).select_from(Signal)),
                "spent_usd": budget.spent()}
