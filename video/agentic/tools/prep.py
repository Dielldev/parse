"""Pack the captures in video/agentic/data into data/film.json, the only data file the film reads, and copy the scout
footage frames the film actually shows into footage/used/ (the speed ramp below decides which).

  .venv/bin/python video/agentic/tools/prep.py
"""
from __future__ import annotations

import bisect
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILM = ROOT / "video" / "agentic"
D = FILM / "data"
OLD = ROOT / "video" / "src" / "data"          # the earlier film's captures: canal replay (watch) + trace

FPS, SUB = 60, 3
# Scout footage speed ramp: film time (s) -> run time (s). Monotone cubic between keys (see film.js rampAt).
RAMP = [[2.00, 0.55], [2.45, 1.40], [3.30, 3.30], [5.55, 26.4], [6.50, 49.7]]


def mono_cubic(keys):
    xs, ys = [k[0] for k in keys], [k[1] for k in keys]
    n = len(keys)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else 3 * (d[i - 1] + d[i]) / ((2 * d[i] + d[i - 1]) / d[i - 1] + (d[i] + 2 * d[i - 1]) / d[i]) for i in range(1, n - 1)] + [d[-1]]

    def f(x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        i = max(0, bisect.bisect_right(xs, x) - 1)
        h = xs[i + 1] - xs[i]
        t = (x - xs[i]) / h
        h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
        return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1]
    return f


def main():
    scout = json.loads((D / "scout.json").read_text())
    agents = json.loads((D / "agents.json").read_text())
    ask = json.loads((D / "ask.json").read_text())
    sig = json.loads((D / "signals.json").read_text())
    watch = json.loads((OLD / "watch_state.json").read_text())
    hashes = dict(line.split("|") for line in (D / "hashes.txt").read_text().split() if "|" in line)

    # ---------------- scout footage: frames used by the ramp, at every render sample
    frames = scout["frames"]
    ft = [f["t"] for f in frames]
    ramp = mono_cubic(RAMP)
    shutter = 0.5 / FPS
    offs = [(-0.5 + k / (SUB - 1)) * shutter for k in range(SUB)] + [0.0]
    used = {}
    t, end = RAMP[0][0] - 0.2, RAMP[-1][0] + 1.2
    n = int(round(t * FPS))
    while n / FPS <= end:
        for o in offs:
            tau = ramp(n / FPS + o)
            i = max(0, bisect.bisect_right(ft, tau) - 1)
            used[i] = frames[i]
        n += 1
    for k in (0, 30):    # also cover 30 fps drafts
        pass
    out_dir = FILM / "footage" / "used"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    for i in sorted(used):
        shutil.copy(FILM / "footage" / "scout" / frames[i]["f"], out_dir / frames[i]["f"])
    print(f"footage: {len(used)} of {len(frames)} frames used → {out_dir.relative_to(ROOT)}")

    ev = scout["events"]
    posts = [e for e in ev if e["t"] == "post"]
    scout_out = {
        "run_id": scout["run_id"], "topic": scout["topic"], "ramp": RAMP,
        "frames": [[f["t"], f["f"]] for i, f in enumerate(frames) if i in used],
        "steps": [{"at": e["at"], "action": e["action"], "text": e["text"]} for e in ev if e["t"] == "step"],
        "urls": [{"at": e["at"], "url": e["url"]} for e in ev if e["t"] == "url"],
        "targets": [{"at": e["at"], "title": e["title"], "meta": e["meta"]} for e in ev if e["t"] == "target_info"],
        "posts": [{"at": p["at"], "matched": p["matched"], "kept": p["kept"], "tags": p["tags"],
                   "author": p.get("author"), "text": (p.get("text") or "")[:220], "time": p.get("time"),
                   "views": p.get("views"), "sha": hashes.get(p.get("signal_id") or "", "")} for p in posts],
        "end": next(e for e in ev if e["t"] == "end"),
    }

    # ---------------- field agents: one lane per source, from the real event log
    aev = agents["events"]
    start = aev[0]
    srcs = {s["id"]: s for s in start["sources"]}
    lanes = {}
    for e in aev:
        sid = e.get("source")
        if not sid or sid not in srcs:
            continue
        L = lanes.setdefault(sid, {"id": sid, "name": srcs[sid]["name"], "tier": srcs[sid]["tier"],
                                   "method": srcs[sid]["method"], "t0": None, "t1": None, "gets": [], "items": [],
                                   "state": None, "note": "", "seen": 0, "kept": 0})
        if e["t"] == "source" and e.get("state") == "visiting":
            L["t0"] = e["at"]
        elif e["t"] == "source":
            L["t1"], L["state"], L["note"] = e["at"], e["state"], e.get("note", "")
            L["seen"], L["kept"] = e.get("seen", 0), e.get("kept", 0)
        elif e["t"] == "note" and e["text"].startswith("GET "):
            L["gets"].append({"at": e["at"], "url": e["text"][4:]})
        elif e["t"] == "item":
            L["items"].append({"at": e["at"], "title": e["title"], "lang": e["lang"], "date": e["date"],
                               "sha": hashes.get(e["id"], "")})
    lanes = sorted(lanes.values(), key=lambda L: (L["t0"] if L["t0"] is not None else 99, L["name"]))
    agents_out = {"run_id": agents["run_id"], "terms": start["terms"], "elapsed": aev[-1]["at"],
                  "kept": aev[-1]["kept"], "workers": 8, "lanes": lanes}

    # ---------------- signals: real Qwen3-8B outputs on 29 Nov 2024 + the replay's funnel and its P1 story
    by_id = {p["id"]: p for p in sig["labelled"]}
    pick = ["sig_01JDWQCPS02M7H1MS45EQJ3GFY"]   # placeholder so the list below can be edited by id
    rows = []
    want = [  # (title start, keep?)  chosen to show both outcomes, in four languages
        "Kosovski MUP odlučio", "Нови притисак Приштине", "PDK paralajmëron padi", "Tajvani heq regjimin",
        "Pas shpërthimeve me granata", "Detonacija u Donjim Varagama", "Снажна експлозија у Зубином",
        "Експлозија у Зубином Потоку"]
    for w in want:
        p = next(x for x in sig["labelled"] if x["title"].startswith(w))
        o = p["out"]
        rows.append({"id": p["id"], "title": p["title"], "lang": p["lang"], "source": p["source"], "tier": p["tier"],
                     "when": p["when"], "model": p["model"], "relevant": bool(o.get("is_threat_relevant")),
                     "labels": o.get("labels", []), "narratives": o.get("narratives", []),
                     "places": o.get("places", [])[:4], "orgs": o.get("orgs", [])[:3],
                     "intent": (o.get("offline_intent") or {}).get("span") or ""})
    story = next(s for s in watch["stories"] if s.get("alert"))
    signals_out = {"total": ask_total(ask), "langs": sig["langs"], "sources": sig["sources"],
                   "labelled_window": len(sig["labelled"]),
                   "labelled_relevant": sum(1 for p in sig["labelled"] if p["out"].get("is_threat_relevant")),
                   "rows": rows,
                   "funnel": {"posts": watch["totals"]["posts"], "kosovo": watch["totals"]["kosovo"],
                              "stories": watch["totals"]["stories"], "traced": watch["totals"]["traced_stories"],
                              "alerts": watch["totals"]["alerts"]},
                   "story": {k: story[k] for k in ("id", "event_id", "title", "posts", "sources", "langs", "first",
                                                   "priority", "tps", "verdict", "origin", "alert", "timeline")},
                   "replay": {"window": watch["window"], "from": "2024-11-29T12:00:00Z", "to": "2024-11-29T21:00:00Z"}}

    # ---------------- ask
    steps = [e for e in ask["events"] if e["type"] == "step"]
    answer = next(e for e in ask["events"] if e["type"] == "answer")
    ask_out = {"q": ask["q"], "window": ask["window"], "steps": steps, "answer": answer}

    film = {"scout": scout_out, "agents": agents_out, "signals": signals_out, "ask": ask_out,
            "kmap": (D / "kmap.svg.html").read_text()}
    (D / "film.json").write_text(json.dumps(film, ensure_ascii=False, default=str))
    print("film.json", f"{(D / 'film.json').stat().st_size:,} bytes")


def ask_total(ask) -> int:
    s = next(e for e in ask["events"] if e.get("id") == "search")
    return int(s["rows"][0][1].split()[0].replace(",", ""))


if __name__ == "__main__":
    main()
