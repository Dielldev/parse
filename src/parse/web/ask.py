"""Ask Parse: answer a question from the collected corpus and show every step it took.

Each step is yielded as soon as it finishes, so the web page can draw the workflow live. Nothing here calls a
paid model: search, ranking, hash checks and source spread are deterministic and run locally. Threat labels are
read from the database if the pipeline already wrote them; this module never triggers a classifier run.

Every step also says, for the copilot view:
  explain  what the step does, in plain words
  ai       where a model touched it: state "used" (its output is part of this answer), "available" (a model
           stage exists here but has not run), or "none" (rules and arithmetic only)
  items    the concrete records it produced, each linking to its page
  links    the other Parse pages that go deeper on this step
"""
from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode

from sqlalchemy import func, or_, select

from parse.db import session
from parse.evidence import verify
from parse import budget
from parse.models import Evidence, LlmOutput, Signal, Source
from parse.normalise.text import fold
from parse.settings import ROOT

TIER_NAMES = {0: "Official / primary", 1: "Established outlet", 2: "Specialist OSINT", 3: "Partisan or unverified"}
MAX_TERMS = 6
CANDIDATES = 1500   # rows pulled for ranking; the match count itself is exact
TOP_K = 8
AGENT_LIMIT = 5        # new items per source when Ask sends agents
AGENT_BUDGET_S = 15.0  # Ask waits at most this long for agents before searching

STOP = set("""
a an and are as at be by can did do does for from had has have how i in is it its me of on or show tell that the
their there these this those to was were what when where which who why will with about any around find give latest
news recent report reports say said says me my our happened happen happening going latest update updates
know anything everything thing things situation regarding been being into over please could would should
dhe ne në te të per për nga me se si qe që cfare çfarë kush ku kur pse eshte është jane janë
i u na za od da je su se sta šta ko gde kada zašto kako ili koji koja koje
""".split())

# Folded Latin letter -> regex class that also matches the diacritic forms used in sq / sr-Latn.
_CLASS = {"c": "[cčć]", "s": "[sš]", "z": "[zž]", "e": "[eë]"}


def terms_of(q: str) -> list[str]:
    words = re.findall(r"[^\W_]{3,}", fold(q))
    seen: list[str] = []
    for w in words:
        if w not in STOP and w not in seen:
            seen.append(w)
    return seen[:MAX_TERMS]


def term_regex(term: str) -> str:
    out, i = [], 0
    while i < len(term):
        if term.startswith("dj", i):
            out.append("(dj|đ)")
            i += 2
            continue
        ch = term[i]
        out.append(_CLASS.get(ch, re.escape(ch)))
        i += 1
    return "".join(out)


def _snippet(text: str, terms: list[str], width: int = 150) -> str:
    """Excerpt around the first matching term, located on the folded text with a char index map."""
    if not text:
        return ""
    folded, idx = [], []
    for i, ch in enumerate(text):
        f = fold(ch)
        folded.append(f)
        idx.extend([i] * len(f))
    ftext = "".join(folded)
    hits = [p for p in (ftext.find(t) for t in terms) if p >= 0]
    if not hits:
        return re.sub(r"\s+", " ", text[: width * 2]).strip()
    at = idx[min(hits)]
    lo, hi = max(0, at - width), min(len(text), at + width)
    s = re.sub(r"\s+", " ", text[lo:hi]).strip()
    return ("…" if lo else "") + s + ("…" if hi < len(text) else "")


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s\-_.]+", name) if p and p[0].isalnum()]
    return ("".join(p[0] for p in parts[:2]) or name[:2]).upper()


def _ai(state: str, what: str, model: str | None = None) -> dict:
    return {"state": state, "model": model, "what": what}


NO_MODEL = "Rules and arithmetic only. No language model ran in this step."


def _model_id(role: str) -> str | None:
    try:
        return budget.model(role)["id"]
    except Exception:  # noqa: BLE001 - config missing a role should not break Ask
        return None


def _href(path: str, **params) -> str:
    q = {k: v for k, v in params.items() if v not in (None, "")}
    return path + ("?" + urlencode(q) if q else "")


def _source_picks(scored: list, top: list, score_of: dict, per_src: Counter, srcs: dict) -> dict:
    """Which sources made it into the answer and why, and why the others did not.

    scored is every ranked match as (score, timestamp, row), best first; top is what the brief cites.
    """
    cutoff = min(score_of.values()) if score_of else 0
    best, above, picked_n = {}, Counter(), Counter(r[3] for r in top)
    for sc, _, r in scored:
        best.setdefault(r[3], sc)
        if sc >= cutoff:
            above[r[3]] += 1
    order = list(dict.fromkeys(r[3] for r in top))   # sources in the order they first appear in the brief

    def card(sid: str) -> dict:
        m = srcs[sid]
        return {"id": sid, "name": m["name"], "tier": m["tier"], "tier_name": TIER_NAMES[m["tier"]],
                "platform": m["platform"], "lang": m["lang"], "matched": per_src[sid], "best": best.get(sid, 0),
                "href": _href("/signals", source=sid)}

    picked = []
    for sid in order:
        c = card(sid)
        c["picked"] = picked_n[sid]
        left = above[sid] - picked_n[sid]
        c["why"] = (f"Best item scored {c['best']} pts; {c['picked']} of its {c['matched']} matches made the top {len(top)}"
                    + ((f", {left} more left out by the 2-per-source cap." if c["picked"] >= 2
                        else f", {left} more tied at the cut-off but the top {len(top)} was already full.")
                       if left > 0 else "."))
        picked.append(c)
    skipped = []
    for sid in sorted((x for x in per_src if x not in picked_n), key=lambda x: (-best.get(x, 0), -per_src[x])):
        c = card(sid)
        c["picked"] = 0
        b = c["best"]
        c["why"] = (f"Tied with the cut-off at {b} pts; newer items from other sources came first." if b == cutoff
                    else f"Best item scored {b} pts, below the cut-off of {cutoff} pts.")
        skipped.append(c)
    return {"picked": picked, "skipped": skipped, "cutoff": cutoff, "considered": len(per_src)}


def _agents_step(terms: list[str]) -> dict:
    """Send field agents to every live-readable news/official source for these terms, wait (bounded), report."""
    from parse.agents import runner
    from parse.agents.methods import method_for

    t0 = time.perf_counter()
    run_id = runner.start("web", " ".join(terms), None, limit=AGENT_LIMIT, origin="ask", fetch_full=False,
                          budget_s=AGENT_BUDGET_S, http_timeout=8.0)
    run = runner.wait(run_id, AGENT_BUDGET_S + 3)
    stats = dict(run["stats"])
    kept = len(run["signal_ids"])
    with session() as s:
        names = {x.source_id: (x.name, x.tier, method_for(x))
                 for x in s.scalars(select(Source).where(Source.source_id.in_(list(stats) or [""])))}
    by_state = Counter(v["state"] for v in stats.values())
    top = sorted(stats.items(), key=lambda kv: -kv[1].get("kept", 0))
    return {"type": "step", "id": "agents", "ms": round((time.perf_counter() - t0) * 1000, 1),
            "title": "Field agents", "subtitle": f"{len(stats)} live sources", "icon": "send",
            "status": "ok" if kept else ("warn" if by_state.get("error") else "empty"),
            "summary": f"{kept} new items from {sum(1 for v in stats.values() if v.get('kept'))} sources"
                       + ("" if run["done"].is_set() else " · slow ones keep going in the background"),
            "rows": [["sent to", f"{len(stats)} sources (site search API + RSS feeds)"],
                     ["kept", f"{kept} new items, archived and searchable now"],
                     ["outcome", ", ".join(f"{k} {v}" for k, v in by_state.most_common())],
                     ["run", run_id]],
            "table": {"cols": ["Source", "Method", "Read", "New"],
                      "rows": [[names.get(sid, (sid,))[0], v["method"], v.get("seen", 0), v.get("kept", 0)]
                               for sid, v in top[:15]]},
            "explain": "Field agents visit the live news and official sources in the registry, read their site "
                       "search and RSS feeds for these words, and archive anything new before Parse searches.",
            "ai": _ai("none", "Agents fetch pages over HTTP and match words. No model reads or rewrites them."),
            "items": [{"title": names.get(sid, (sid,))[0], "sub": f"{v['method']} · read {v.get('seen', 0)}",
                       "tag": f"+{v.get('kept', 0)}", "href": _href("/signals", source=sid)}
                      for sid, v in top[:8] if v.get("kept")],
            "links": [{"label": "Open this run on the Agents page", "href": _href("/agents", topic=" ".join(terms))}],
            "run_id": run_id, "kept": kept}


def run(q: str, window: str = "", lang: str = "", fresh: bool = False) -> Iterator[dict]:
    t_all = time.perf_counter()

    def step(sid: str, t0: float, **kw) -> dict:
        return {"type": "step", "id": sid, "ms": round((time.perf_counter() - t0) * 1000, 1), **kw}

    # 1. trigger
    t0 = time.perf_counter()
    yield step("trigger", t0, title="Question", subtitle="Chat trigger", icon="bolt", status="ok",
               summary=q, rows=[["question", q], ["window", window or "all"], ["language", lang or "all"]],
               explain="Parse takes the question as typed, with the time window and language filters set in the "
                       "composer. Nothing is sent anywhere outside this machine.",
               ai=_ai("none", NO_MODEL),
               links=[{"label": f"Window: {window}", "href": _href("/signals", window=window)}] if window else [])

    # 2. normalise
    t0 = time.perf_counter()
    terms = terms_of(q)
    if not terms:
        yield step("normalise", t0, title="Normalise", subtitle="Fold scripts", icon="type", status="error",
                   summary="No searchable words (need 3+ letters, not a stop word).", rows=[],
                   explain="Parse drops short words and common words in Albanian, Serbian and English. Nothing "
                           "was left to search for.", ai=_ai("none", NO_MODEL))
        yield {"type": "answer", "headline": "I need a name, place or topic to search for.",
               "bullets": ["Try something like “Banjska attack”, “Ibar-Lepenac canal” or “Gazimestan”."],
               "citations": [], "ms": round((time.perf_counter() - t_all) * 1000)}
        return
    yield step("normalise", t0, title="Normalise", subtitle="Fold scripts", icon="type", status="ok",
               summary=f"{len(terms)} term{'' if len(terms) == 1 else 's'} · Latin + Cyrillic + diacritics",
               rows=[["terms", ", ".join(terms)],
                     ["scripts", "Latin, and Serbian Cyrillic via the transliterated text"],
                     ["diacritics", "c ↔ č ć, s ↔ š, z ↔ ž, e ↔ ë, dj ↔ đ"]],
               explain="The question is cut into search terms. Accents are folded so “Zvečan”, “Zvecan” and "
                       "“Звечан” all match, and filler words in three languages are dropped.",
               ai=_ai("none", NO_MODEL),
               links=[{"label": f"“{t}” in Signals", "href": _href("/signals", q=t)} for t in terms[:3]])

    # 2b. field agents (only when asked for fresh reports): new items land in the archive before the search
    agent_kept = None
    if fresh:
        ag = _agents_step(terms)
        agent_kept = ag["kept"]
        yield ag

    with session() as s:
        # 3. registry
        t0 = time.perf_counter()
        by_tier = dict(s.execute(select(Source.tier, func.count()).where(Source.mvp_collect == "yes")
                                 .group_by(Source.tier)).all())
        n_reg = sum(by_tier.values())
        yield step("registry", t0, title="Source registry", subtitle="Allow-list", icon="book", status="ok",
                   summary=f"{n_reg} collected sources",
                   rows=[[f"Tier {t}", f"{by_tier.get(t, 0)} · {TIER_NAMES[t]}"] for t in range(4)],
                   explain="Parse only searches sources on its allow-list. Each source has a tier, from official "
                           "and primary (Tier 0) to partisan or unverified (Tier 3), and the tier travels with "
                           "every item it publishes.",
                   ai=_ai("none", "The registry is a hand-checked list. No model chose or rated these sources."),
                   items=[{"title": f"Tier {t} · {TIER_NAMES[t]}", "sub": f"{by_tier.get(t, 0)} sources",
                           "tag": f"T{t}", "href": _href("/sources", tier=t)} for t in range(4)],
                   links=[{"label": "Source registry", "href": "/sources"}])

        # 4. search
        t0 = time.perf_counter()
        cols = (Signal.title, Signal.text_original, Signal.text_latin, Signal.text_en)
        cond = or_(*[c.op("~*")(term_regex(t)) for t in terms for c in cols])
        base = select(Signal.signal_id).where(cond)
        if window:
            base = base.where(Signal.window == window)
        if lang:
            base = base.where(Signal.lang == lang)
        n_total = s.scalar(select(func.count()).select_from(Signal))
        n_match = s.scalar(select(func.count()).select_from(base.subquery()))
        rows = s.execute(
            select(Signal.signal_id, Signal.title, func.substr(func.coalesce(Signal.text_latin, Signal.text_original), 1, 6000),
                   Signal.source_id, Signal.published_at, Signal.lang, Signal.window, Signal.evidence_sha256,
                   Signal.labels, Signal.narratives, Signal.url, Signal.text_en.is_not(None))
            .where(Signal.signal_id.in_(base.order_by(Signal.published_at.desc().nulls_last()).limit(CANDIDATES)))
        ).all()
        n_en = sum(1 for r in rows if r[11])
        tr_model = _model_id("translation")
        yield step("search", t0, title="Search corpus", subtitle="Postgres", icon="database",
                   status="ok" if n_match else "empty",
                   summary=f"{n_match:,} of {n_total:,} signals match",
                   rows=[["scanned", f"{n_total:,} signals"], ["matched", f"{n_match:,}"],
                         ["ranked", f"{len(rows):,} most recent"],
                         ["fields", "title, original text, Latin transliteration, English translation"]],
                   explain="Every archived item is checked against the terms: title, original text, its Latin "
                           "transliteration and, where one exists, its English translation. The count is exact; "
                           "the newest matches go on to ranking.",
                   ai=_ai("used", f"{n_en} of the matched items carry an English translation written by "
                                  f"{tr_model or 'the translation model'}, and search also read that text.", tr_model)
                   if n_en else _ai("none", "Plain pattern matching in Postgres. None of the matched items has a "
                                            "machine translation, so no model output was searched."),
                   links=[{"label": "Open these matches in Signals",
                           "href": _href("/signals", q=terms[0], window=window, lang=lang)}])
        if not n_match:
            yield {"type": "answer", "headline": f"Nothing in the corpus mentions {', '.join(terms)}.",
                   "bullets": ["Parse only searches sources in its registry and the backfill windows collected so far.",
                               "Try another spelling, or clear the window and language filters."],
                   "citations": [], "agents": {"topic": " ".join(terms), "sent": fresh, "kept": agent_kept},
                   "ms": round((time.perf_counter() - t_all) * 1000)}
            return

        # 5. sources (fan-out)
        t0 = time.perf_counter()
        per_src = Counter(r[3] for r in rows)
        srcs = {x.source_id: {"name": x.name, "tier": x.tier, "platform": x.platform, "lang": x.lang}
                for x in s.scalars(select(Source).where(Source.source_id.in_(list(per_src))))}
        branches = [{"id": sid, "name": srcs[sid]["name"], "tier": srcs[sid]["tier"], "platform": srcs[sid]["platform"],
                     "lang": srcs[sid]["lang"], "count": n, "initials": _initials(srcs[sid]["name"])}
                    for sid, n in per_src.most_common(5)]
        yield step("sources", t0, title="Fetch from sources", subtitle=f"{len(per_src)} sources", icon="globe",
                   status="ok", summary=f"{len(per_src)} sources returned matches", branches=branches,
                   table={"cols": ["Source", "Tier", "Platform", "Matches"],
                          "rows": [[srcs[sid]["name"], "T" + str(srcs[sid]["tier"]), srcs[sid]["platform"], n]
                                   for sid, n in per_src.most_common(15)]},
                   explain="The matches are grouped by the outlet that published them, so you can see who is "
                           "talking about this and how much.",
                   ai=_ai("none", NO_MODEL),
                   items=[{"title": srcs[sid]["name"], "sub": f"{srcs[sid]['platform']} · {srcs[sid]['lang'] or '?'}",
                           "tag": f"T{srcs[sid]['tier']} · {n}", "href": _href("/signals", source=sid, q=terms[0])}
                          for sid, n in per_src.most_common(12)],
                   links=[{"label": "Source registry", "href": "/sources"}])

    # 6. rank
    t0 = time.perf_counter()
    main_window = Counter(r[6] for r in rows if r[6]).most_common(1)
    main_window = main_window[0][0] if main_window else None
    scored = []
    for r in rows:
        title_f, body_f = fold(r[1] or ""), fold(r[2] or "")
        sc = sum(3 * title_f.count(t) + min(body_f.count(t), 5) for t in terms) + (2 if r[6] == main_window else 0)
        scored.append((sc, r[4].timestamp() if r[4] else 0, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top, seen_src, score_of = [], Counter(), {}
    for sc, _, r in scored:   # at most 2 per source so one outlet cannot fill the brief
        if seen_src[r[3]] < 2:
            top.append(r)
            score_of[r[0]] = sc
            seen_src[r[3]] += 1
        if len(top) == TOP_K:
            break
    picks = _source_picks(scored, top, score_of, per_src, srcs)
    n_picked = len(picks["picked"])
    yield step("rank", t0, title="Rank & pick sources", subtitle="Term hits", icon="sort", status="ok",
               summary=f"Picked {len(top)} items from {n_picked} of {len(per_src)} sources: "
                       + ", ".join(x["name"] for x in picks["picked"][:4]) + ("…" if n_picked > 4 else ""),
               rows=[["scoring", "3 × hits in title + hits in body (capped at 5)"],
                     ["burst bonus", f"+2 for the window with most coverage ({main_window or 'none'})"],
                     ["diversity", "at most 2 items from any one source"], ["kept", str(len(top))],
                     ["cut-off", f"{picks['cutoff']} pts: the lowest score that made the top {len(top)}"]],
               picks=picks,
               explain="Each match gets points for the terms in its title (worth 3) and body (capped at 5), plus 2 "
                       "if it sits in the window with the most coverage. The best items win, but no outlet may fill "
                       "more than two places, so the answer draws on several sources. Each source below says why it "
                       "was picked or left out.",
               ai=_ai("none", "A fixed scoring formula, not a model. The same inputs always give the same order."),
               items=[{"title": r[1] or "(no title)", "sub": f"{srcs[r[3]]['name']} · "
                       + (f"{r[4]:%d %b %Y}" if r[4] else "undated"), "tag": f"{score_of[r[0]]} pts",
                       "href": f"/signals/{r[0]}"} for r in top])

    # 7. evidence
    t0 = time.perf_counter()
    with session() as s:
        evs = {e.sha256: e for e in s.scalars(select(Evidence).where(
            Evidence.sha256.in_([r[7] for r in top if r[7]])))}
    ok, ev_items = 0, []
    for r in top:
        e, good = evs.get(r[7]), False
        if e is not None:
            p: Path = ROOT / e.html_uri
            good = bool(p.exists() and verify(p, e.sha256))
            ok += good
        ev_items.append({"title": r[1] or "(no title)", "sub": (r[7] or "no archive")[:16] + ("…" if r[7] else ""),
                         "tag": "intact" if good else ("mismatch" if e is not None else "missing"),
                         "state": "ok" if good else "bad",
                         "href": f"/evidence/{r[7]}/text" if e is not None and e.text_uri else f"/signals/{r[0]}"})
    yield step("evidence", t0, title="Evidence vault", subtitle="SHA-256", icon="lock",
               status="ok" if ok == len(top) else "warn",
               summary=f"{ok}/{len(top)} archived pages match their hash",
               rows=[["checked", str(len(top))], ["intact", str(ok)], ["store", "write-once, served as plain text"]],
               explain="When Parse collects a page it stores a copy and its SHA-256 fingerprint. Here it re-reads "
                       "each copy behind the top items and checks the fingerprint, so you know the page has not "
                       "changed since it was collected.",
               ai=_ai("none", "A cryptographic hash check. No model is involved."),
               items=ev_items)

    # 8. labels (read only)
    t0 = time.perf_counter()
    lab = Counter(l for r in top for l in (r[8] or []))
    nar = Counter(n for r in top for n in (r[9] or []))
    with session() as s:
        outs = s.execute(select(LlmOutput.subject_id, LlmOutput.stage, LlmOutput.model, LlmOutput.usd)
                         .where(LlmOutput.subject_id.in_([r[0] for r in top]))).all()
    by_model = Counter((o[1], o[2]) for o in outs)
    usd = sum(o[3] or 0 for o in outs)
    det_model = _model_id("detector")
    labelled = [r for r in top if r[8] or r[9]]
    cls_links = [{"label": "All labelled signals", "href": _href("/signals", labelled="yes")},
                 {"label": "How labels feed the threat score", "href": "/how-it-works"},
                 {"label": "Labelling progress", "href": "/overview"}]
    if lab or nar:
        writers = ", ".join(sorted({m for (_, m) in by_model})) or det_model or "the classifier"
        yield step("classify", t0, title="Threat labels", subtitle="Qwen classifier", icon="spark", status="ok",
                   summary=", ".join(f"{k}×{v}" for k, v in (lab + nar).most_common(4)),
                   rows=[[k, f"{v} of {len(top)}"] for k, v in (lab + nar).most_common(10)]
                   + [[f"{st} · {m}", f"{n} outputs" ] for (st, m), n in by_model.most_common()]
                   + ([["cost on record", f"${usd:.5f}"]] if outs else []),
                   explain="Threat (T1-T10) and narrative (N1-N11) labels on the top items. A model wrote them "
                           "earlier in the pipeline; Ask only reads them back, so check the cited items before "
                           "you rely on a label.",
                   ai=_ai("used", f"{len(labelled)} of {len(top)} top items carry labels written by {writers}. "
                                  "Ask read them; it did not call the model now.", writers),
                   items=[{"title": r[1] or "(no title)", "sub": srcs[r[3]]["name"],
                           "tag": " ".join((r[8] or []) + (r[9] or []))[:40], "href": f"/signals/{r[0]}"}
                          for r in labelled],
                   links=cls_links)
    else:
        yield step("classify", t0, title="Threat labels", subtitle="Qwen classifier", icon="spark", status="skip",
                   summary="Not labelled yet · paid run, skipped",
                   rows=[["status", "None of these signals has labels in the database yet."],
                         ["why skipped", "Classifier calls are billed on Featherless and need approval (--approve)."]],
                   explain="This is where a model would mark each item with threat and narrative labels. None of "
                           "the top items has been labelled yet, and Ask never starts a paid model run on its own.",
                   ai=_ai("available", "A model stage sits here but has not run on these items, so no model "
                                       "output is in this answer.", det_model),
                   links=cls_links)

    # 9. spread
    t0 = time.perf_counter()
    tiers = Counter(srcs[r[3]]["tier"] for r in rows)
    best = min(tiers) if tiers else None
    yield step("spread", t0, title="Source spread", subtitle="Independence", icon="branch", status="ok",
               summary=f"{len(per_src)} outlets · best Tier {best}",
               rows=[[f"Tier {t}", f"{tiers.get(t, 0)} signals"] for t in range(4)]
               + [["note", "Outlets are counted, not verified claims. Verdicts come from the verifier stage."]],
               explain="How many separate outlets carried the story, and the most trusted tier among them. Wide, "
                       "high-tier coverage is a stronger signal than one partisan outlet repeating itself.",
               ai=_ai("none", NO_MODEL),
               items=[{"title": f"Tier {t} · {TIER_NAMES[t]}", "sub": f"{tiers.get(t, 0)} ranked items",
                       "tag": f"T{t}", "href": _href("/sources", tier=t)} for t in range(4) if tiers.get(t)],
               links=[{"label": "Verdict rules (How it works)", "href": "/how-it-works"}])

    # 10. answer
    t0 = time.perf_counter()
    dated = sorted((r for r in rows if r[4]), key=lambda r: r[4])
    by_window = Counter(r[6] or "live" for r in rows)
    by_day = Counter(r[4].date() for r in dated)
    bullets = []
    if dated:
        first = dated[0]
        bullets.append(f"Earliest mention: {first[4]:%d %b %Y} by {srcs[first[3]]["name"]} (Tier {srcs[first[3]]["tier"]}).")
        day, n = by_day.most_common(1)[0]
        bullets.append(f"Busiest day: {day:%d %b %Y} with {n} items.")
    w, n = by_window.most_common(1)[0]
    bullets.append(f"Most coverage sits in the {w} window ({n} of {len(rows)} ranked items).")
    langs = Counter(r[5] or "?" for r in rows)
    bullets.append("Languages: " + ", ".join(f"{k} {v}" for k, v in langs.most_common(4)) + ".")
    bullets.append(f"Picked {len(top)} items from {len(picks['picked'])} of {len(per_src)} matching sources: "
                   + ", ".join(f"{x['name']} (T{x['tier']})" for x in picks["picked"]) + ".")
    if best is not None:
        tier0 = [v["name"] for v in srcs.values() if v["tier"] == 0][:3]
        bullets.append(f"Highest-tier source: Tier {best}" + (f" ({', '.join(tier0)})." if tier0 else "."))
    cites = [{"n": i + 1, "id": r[0], "title": r[1] or "(no title)", "source": srcs[r[3]]["name"], "source_id": r[3],
              "tier": srcs[r[3]]["tier"], "date": f"{r[4]:%d %b %Y}" if r[4] else "undated", "lang": r[5] or "?",
              "window": r[6] or "live", "url": r[10], "snippet": _snippet(r[2] or "", terms)}
             for i, r in enumerate(top)]
    yield step("brief", t0, title="Write brief", subtitle="Deterministic", icon="file", status="ok",
               summary=f"{len(bullets)} findings · {len(cites)} citations",
               rows=[["method", "Counts and dates from the matches; no language model wrote this answer."]],
               explain="The answer is assembled from counts and dates in the matches: who reported first, the "
                       "busiest day, the languages and the best source tier. Every line traces back to a cited item.",
               ai=_ai("none", "Written by fixed templates from the numbers above. No language model wrote this answer."),
               items=[{"title": c["title"], "sub": f"{c['source']} · {c['date']}", "tag": f"/{c['n']}",
                       "href": f"/signals/{c['id']}"} for c in cites])
    yield {"type": "answer",
           "headline": f"{n_match:,} signals from {len(per_src)} sources mention {', '.join(terms)}.",
           "bullets": bullets, "citations": cites, "sources": picks, "agents": {"topic": " ".join(terms), "sent": fresh, "kept": agent_kept},
           "ms": round((time.perf_counter() - t_all) * 1000)}
