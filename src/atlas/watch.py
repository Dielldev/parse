"""A0 Watcher: the automation that keeps Atlas looking at the accounts that post about Kosovo.

Every cycle:
  1 collect   Live: field agents visit every live account in the registry (news, official and mirror sites;
              Telegram and X are later phases) and archive what is new. Replay: the next slice of an archived
              window is released in time order, as if it were happening now (the brief's back-test).
  2 filter    keep posts about Kosovo
  3 group     join each post to an open story (same wording, close meaning, or the same names and places in any
              language), or open a new story
  4 trace     run the Tracer on stories that grew: earliest observed source, spread graph, amplifiers, score,
              verdict. One Event per story, rewritten as it grows. In replay the Tracer sees only what was
              published by the replay clock.
  5 alert     a story that reaches P1/P2 raises an Alert, with the time it took from the first post

The dashboard (/watch) polls state() and shows all of it. Nothing here calls a paid model unless "check claims"
is switched on, in which case the Tracer's stance checks and brief use the Qwen models.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

import yaml
from sqlalchemy import func, select

from atlas import tracer as T
from atlas.db import session
from atlas.ids import new_id
from atlas.models import Alert, Signal, Source
from atlas.normalise.text import is_kosovo_relevant
from atlas.settings import CONFIG_DIR, thresholds

STAGES = ("collect", "filter", "group", "trace", "alert")
LIVE_TOPIC = "Kosovo Kosova Kosovë Kosovu Косово Kosovska Prishtina Priština Mitrovica"


def cfg() -> dict:
    return thresholds()["watch"]


def windows() -> dict:
    return yaml.safe_load((CONFIG_DIR / "windows.yaml").read_text())["windows"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d):
    return d.isoformat() if d else None


class Story:
    def __init__(self, sid: str, n: T.Node, stems: set[str]):
        self.id = sid
        self.nodes: list[T.Node] = [n]
        self.stems = set(stems)
        self.vec = list(n.vec) if n.vec else None
        self.title = n.title
        self.first = n.when
        self.last = n.when
        self.traced_n = 0
        self.event_id: str | None = None
        self.result: dict | None = None
        self.alert: dict | None = None
        self.opened_at = None
        self.traces = 0
        self.ai_n = 0   # story size at its last model check

    def add(self, n: T.Node, stems: set[str]) -> None:
        self.nodes.append(n)
        self.stems |= stems
        if n.vec and self.vec:
            k = len(self.nodes)
            v = [(a * (k - 1) + b) / k for a, b in zip(self.vec, n.vec)]
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            self.vec = [x / norm for x in v]
        elif n.vec:
            self.vec = list(n.vec)
        if n.when and (self.first is None or n.when < self.first):
            self.first, self.title = n.when, n.title
        if n.when and (self.last is None or n.when > self.last):
            self.last = n.when

    @property
    def sources(self) -> set[str]:
        return {n.source_id for n in self.nodes}

    def view(self) -> dict:
        r = self.result or {}
        langs = Counter(n.lang or "?" for n in self.nodes)
        nodes = sorted(self.nodes, key=lambda n: n.when or datetime.max.replace(tzinfo=timezone.utc))
        first_main = next((n for n in nodes if n.tier <= 1), None)
        return {
            "id": self.id, "event_id": self.event_id, "title": self.title, "posts": len(self.nodes),
            "sources": len(self.sources), "langs": dict(langs), "first": _iso(self.first), "last": _iso(self.last),
            "accounts": [x for x, _ in Counter(n.source for n in self.nodes).most_common(6)],
            "timeline": [{"t": _iso(n.when), "lang": n.lang, "tier": n.tier, "source": n.source, "title": n.title[:120],
                          "id": n.id} for n in nodes[:80]],
            "traced": bool(r), "traces": self.traces, "traced_posts": self.traced_n,
            "priority": (r.get("tps") or {}).get("priority"), "tps": (r.get("tps") or {}).get("tps"),
            "verdict": (r.get("verdict") or {}).get("verdict"),
            "verdict_checked": (r.get("verdict") or {}).get("checked"),
            "origin": {k: (r.get("origin") or {}).get(k) for k in ("source", "when", "title", "confidence", "tier",
                                                                   "signal_id")} if r else None,
            "amplifiers": [a["source"] for a in (r.get("amplifiers") or []) if a.get("reach")][:4],
            "graph_posts": len([n for n in (r.get("graph") or {}).get("nodes", []) if not n.get("probe")]),
            "edges": len((r.get("graph") or {}).get("edges", [])),
            "headline": (r.get("brief") or {}).get("headline"),
            "narrative": (r.get("brief") or {}).get("narrative"),
            "acceptance": r.get("acceptance"),
            "steps": [{"id": s["id"], "title": s["title"], "summary": s.get("summary"), "status": s.get("status"),
                       "ms": s.get("ms"), "n": s.get("n")} for s in (r.get("steps") or [])],
            "alert": self.alert,
            "first_mainstream": {"source": first_main.source, "t": _iso(first_main.when)} if first_main else None,
        }


class Watcher:
    def __init__(self):
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.reset()

    def reset(self):
        self.running = False
        self.mode = None
        self.window = None
        self.ai = False
        self.step_min = cfg()["replay_step_minutes"]
        self.interval = cfg()["replay_interval_s"]
        self.clock: datetime | None = None
        self.end: datetime | None = None
        self.cycle = 0
        self.stage = "idle"
        self.stage_counts = {s: 0 for s in STAGES}
        self.totals = Counter()
        self.stories: dict[str, Story] = {}
        self.feed: deque = deque(maxlen=120)
        self.log: deque = deque(maxlen=200)
        self.per_source = Counter()
        self.per_source_kos = Counter()
        self.started_at = None
        self.last_cycle_at = None
        self.next_cycle_at = None
        self.session_id = None
        self.error = None
        self.finished = False
        self.stem_df = Counter()
        self.seen_posts = 0

    # ------------------------------------------------------------------ control
    def start(self, mode: str, window: str | None = None, step_min: int | None = None, interval: float | None = None,
              ai: bool = False, start_at: datetime | None = None, background: bool = True) -> None:
        """Start watching. background=False sets everything up without the loop thread (call run_cycle yourself)."""
        with self.lock:
            if self.running:
                raise RuntimeError("The watcher is already running. Stop it first.")
            self.reset()
            self.mode, self.ai = mode, bool(ai)
            self.session_id = new_id("wch")
            self.started_at = _now()
            if mode == "replay":
                w = windows().get(window or "")
                if not w:
                    raise ValueError(f"Unknown window {window!r}.")
                self.window = window
                self.clock = datetime.fromisoformat(str(w["start"])).replace(tzinfo=timezone.utc)
                self.end = datetime.fromisoformat(str(w["end"])).replace(tzinfo=timezone.utc) + timedelta(days=1)
                if start_at and self.clock <= start_at < self.end:
                    self.clock = start_at
                self.step_min = int(step_min or cfg()["replay_step_minutes"])
                self.interval = float(interval if interval is not None else cfg()["replay_interval_s"])
            elif mode == "live":
                self.clock = _now()
                self.interval = float(interval if interval is not None else cfg()["live_interval_s"])
            else:
                raise ValueError("mode must be live or replay")
            self.running = True
            self.stop_ev.clear()
            self.say(f"Watch started · {'replay of ' + window if mode == 'replay' else 'live accounts'}"
                     + (" · claims checked with Qwen" if ai else " · no model calls"))
            if background:
                self.thread = threading.Thread(target=self._loop, name="atlas-watch", daemon=True)
                self.thread.start()

    def stop(self) -> None:
        with self.lock:
            if self.running:
                self.say("Stopped by the analyst.")
            self.running = False
            self.stop_ev.set()
            self.stage = "idle"

    def say(self, text: str, kind: str = "info") -> None:
        self.log.appendleft({"at": _iso(_now()), "clock": _iso(self.clock), "cycle": self.cycle, "kind": kind,
                             "text": text})

    def _loop(self) -> None:
        while self.running and not self.stop_ev.is_set():
            t0 = time.monotonic()
            try:
                self.run_cycle()
            except Exception as e:  # noqa: BLE001 - a failed cycle is logged; the watch keeps going
                self.error = f"{type(e).__name__}: {e}"
                self.say(f"Cycle {self.cycle} failed: {self.error}", "bad")
            if self.finished:
                self.running = False
                self.stage = "idle"
                break
            wait = max(0.0, self.interval - (time.monotonic() - t0))
            self.next_cycle_at = _iso(_now() + timedelta(seconds=wait))
            self.stop_ev.wait(wait)
        self.next_cycle_at = None

    # ------------------------------------------------------------------ one cycle
    def run_cycle(self) -> None:
        self.cycle += 1
        self.stage_counts = {s: 0 for s in STAGES}
        c = cfg()

        # 1 collect
        self.stage = "collect"
        if self.mode == "replay":
            prev, self.clock = self.clock, self.clock + timedelta(minutes=self.step_min)
            with session() as s:
                rows = s.execute(select(Signal, Source).join(Source).where(
                    Signal.window == self.window, Signal.published_at > prev, Signal.published_at <= self.clock)
                    .order_by(Signal.published_at)).all()
            what = f"released {len(rows)} archived posts from {prev:%d %b %H:%M} to {self.clock:%d %b %H:%M} UTC"
        else:
            from atlas.agents import runner
            prev, self.clock = self.clock, _now()
            run_id = runner.start("web", LIVE_TOPIC, None, limit=c["live_items_per_source"], origin="watch",
                                  fetch_full=False, budget_s=c["live_budget_s"], http_timeout=10.0)
            run = runner.wait(run_id, c["live_budget_s"] + 10)
            ids = list(run["signal_ids"])
            with session() as s:
                rows = s.execute(select(Signal, Source).join(Source).where(Signal.signal_id.in_(ids or [""]))
                                 .order_by(Signal.published_at.nulls_last())).all()
            states = Counter(v.get("state") for v in run["stats"].values())
            what = (f"agents visited {len(run['stats'])} accounts ({', '.join(f'{k} {v}' for k, v in states.items())}), "
                    f"{len(rows)} new posts · run {run_id}")
        self.stage_counts["collect"] = len(rows)
        self.totals["posts"] += len(rows)
        for sg, sr in rows:
            self.per_source[sr.source_id] += 1
        self.say(f"Collect: {what}")

        # 2 filter
        self.stage = "filter"
        kept = [(sg, sr) for sg, sr in rows
                if is_kosovo_relevant(sg.title, (sg.text_latin or sg.text_original or "")[:3000], sg.url)]
        self.stage_counts["filter"] = len(kept)
        self.totals["kosovo"] += len(kept)
        for sg, sr in kept:
            self.per_source_kos[sr.source_id] += 1

        # 3 group
        self.stage = "group"
        nodes = [T._node_from(sg, sr) for sg, sr in kept]   # noqa: SLF001
        if nodes:
            try:
                T._embed(nodes)   # noqa: SLF001 - local, free; stored for the Tracer to reuse
            except Exception as e:  # noqa: BLE001
                self.say(f"Embeddings unavailable ({type(e).__name__}); grouping by wording and names only.", "warn")
        new_stories, joined = 0, 0
        grown: set[str] = set()
        for n in nodes:
            stems = set(T.seed_terms("", n.title, avoid=n.source))
            self.stem_df.update(stems)
            self.seen_posts += 1
            st = self._match(n, stems, c)
            if st is None:
                sid = f"st{len(self.stories) + 1:03d}"
                st = Story(sid, n, stems)
                st.opened_at = _iso(self.clock)
                self.stories[sid] = st
                new_stories += 1
            else:
                st.add(n, stems)
                joined += 1
            grown.add(st.id)
            self.feed.appendleft({"id": n.id, "t": _iso(n.when), "source": n.source, "tier": n.tier, "lang": n.lang,
                                  "platform": n.platform, "title": n.title[:160], "story": st.id, "seen": _iso(self.clock)})
        self.stage_counts["group"] = len(grown)
        self.totals["stories"] = len(self.stories)
        if nodes:
            self.say(f"Group: {len(nodes)} Kosovo posts → {new_stories} new stories, {joined} joined open stories.")

        # 4 trace
        self.stage = "trace"
        ready = [st for st in self.stories.values() if st.id in grown and len(st.nodes) > st.traced_n
                 and len(st.nodes) >= c["trace_min_posts"] and len(st.sources) >= c["trace_min_sources"]]
        ready.sort(key=lambda st: -(len(st.nodes) - st.traced_n))
        for st in ready[:c["traces_per_cycle"]]:
            if not self.running:
                break
            self._trace(st)
        self.stage_counts["trace"] = min(len(ready), c["traces_per_cycle"])

        # 5 alert
        self.stage = "alert"
        raised = 0
        for st in self.stories.values():
            pr = ((st.result or {}).get("tps") or {}).get("priority")
            if pr in ("P1", "P2") and st.alert is None and st.event_id:
                st.alert = self._alert(st)
                raised += 1
        self.stage_counts["alert"] = raised
        self.totals["alerts"] += raised
        self.last_cycle_at = _iso(_now())
        if self.mode == "replay" and self.clock >= self.end:
            self.finished = True
            self.say(f"Replay of {self.window} finished: {len(self.stories)} stories, {self.totals['traced']} traced, "
                     f"{self.totals['alerts']} alerts.", "ok")
        self.stage = "wait"

    def _match(self, n: T.Node, stems: set[str], c: dict) -> Story | None:
        """The open story this post belongs to, or None. Guards against drift: shared wording only counts between
        different outlets, or near-identical text from the same outlet (its template alone is not evidence), names only count when they are rare in
        what the watch has seen (Kurti or Prishtina are everywhere), and meaning must stay close to the story's
        first post as well as its centre."""
        best, best_score = None, 0.0
        horizon = timedelta(hours=c["story_open_hours"])
        common = max(3, int(self.seen_posts * 0.03))
        rare = {x for x in stems if self.stem_df[x] <= common}
        for st in self.stories.values():
            if n.when and st.last and n.when - st.last > horizon:
                continue
            cs = T.cosine(n.vec, st.vec)
            cs_first = T.cosine(n.vec, st.nodes[0].vec)
            ov = 0.0
            for m in st.nodes[-25:]:
                j = T.overlap(n.sh, m.sh)[1]
                ov = max(ov, j if m.source_id != n.source_id or j >= 0.6 else 0.0)   # own template is not evidence
            names = len(rare & st.stems)
            same_lang = n.family == st.nodes[0].family
            ok = ov >= c["join_overlap"] or (same_lang and cs >= c["join_cosine"] and cs_first >= 0.7) \
                or (names >= 2 and cs >= c["join_cosine_names"] and cs_first >= c["join_cosine_names"] - 0.05)
            score = max(ov * 2, cs) + names * 0.02
            if ok and score > best_score:
                best, best_score = st, score
        return best

    def _trace(self, st: Story) -> None:
        seed = min(st.nodes, key=lambda n: n.when or datetime.max.replace(tzinfo=timezone.utc))
        t0 = time.monotonic()
        result = None
        # Model calls (labels, claim checks, brief) only for stories several accounts carry, and again only when
        # the story has grown by half since its last check. Every other trace is local and free.
        deep = self.ai and len(st.sources) >= cfg()["ai_min_sources"] and len(st.nodes) >= 1.5 * st.ai_n
        if deep:
            st.ai_n = len(st.nodes)
        for ev in T.run({"kind": "signal", "signal_id": seed.id, "watch": self.session_id, "story": st.id},
                        ai=deep, until=self.clock if self.mode == "replay" else None, event_id=st.event_id):
            if ev["type"] == "result":
                result = ev
            elif ev["type"] == "error":
                self.say(f"Trace {st.id} failed: {ev['message']}", "bad")
        if result is None:
            return
        prev = st.result
        if prev and not deep and (prev.get("verdict") or {}).get("checked"):
            result["verdict"] = prev["verdict"] | {"note": f"checked at {st.ai_n} posts"}
        st.result, st.event_id, st.traced_n = result, result.get("event_id"), len(st.nodes)
        st.traces += 1
        self.totals["traced"] += 1
        o = result["origin"]
        self.say(f"Trace {st.id}: “{st.title[:70]}” · earliest observed {o['source']} "
                 f"({(o.get('when') or '')[:16].replace('T', ' ')}), {len(result['graph']['edges'])} edges, "
                 f"{result['tps']['priority']} · {result['verdict']['verdict']} · {time.monotonic() - t0:.1f}s", "ok")

    def _alert(self, st: Story) -> dict:
        r = st.result
        b = r["brief"]
        aid = new_id("alr")
        with session() as s:
            s.add(Alert(alert_id=aid, event_id=st.event_id, priority=r["tps"]["priority"],
                        brief=f"{b['headline']} {b['narrative']}", what_we_know=b["what_we_know"],
                        what_we_dont_know=b["what_we_dont_know"], suggested_checks=b["suggested_checks"]))
        lead = (self.clock - st.first).total_seconds() / 60 if st.first else None
        fm = st.view()["first_mainstream"]
        self.say(f"ALERT {r['tps']['priority']} on {st.id}: “{st.title[:70]}”"
                 + (f" · {lead:.0f} min after the first post" if lead is not None else ""), "bad")
        return {"alert_id": aid, "priority": r["tps"]["priority"], "at": _iso(self.clock),
                "minutes_after_first": round(lead) if lead is not None else None, "first_mainstream": fm}

    # ------------------------------------------------------------------ dashboard
    def state(self) -> dict:
        with self.lock:
            stories = sorted((st.view() for st in self.stories.values()),
                             key=lambda v: ({"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(v["priority"] or "", 4),
                                            -v["posts"], v["first"] or ""))
            return {"running": self.running, "mode": self.mode, "window": self.window, "ai": self.ai,
                    "stage": self.stage, "stage_counts": self.stage_counts, "cycle": self.cycle,
                    "clock": _iso(self.clock), "end": _iso(self.end), "step_min": self.step_min,
                    "interval": self.interval, "started_at": _iso(self.started_at), "last_cycle_at": self.last_cycle_at,
                    "next_cycle_at": self.next_cycle_at, "session": self.session_id, "finished": self.finished,
                    "totals": {"posts": self.totals["posts"], "kosovo": self.totals["kosovo"],
                               "stories": len(self.stories), "traced_stories": sum(1 for s in self.stories.values()
                                                                                   if s.result),
                               "traces": self.totals["traced"], "alerts": self.totals["alerts"]},
                    "stories": stories[:60], "feed": list(self.feed)[:60], "log": list(self.log)[:80],
                    "per_source": dict(self.per_source), "per_source_kos": dict(self.per_source_kos),
                    "error": self.error}


WATCHER = Watcher()


def accounts() -> list[dict]:
    """Every account in the registry, whether the watcher can read it live, and what it has posted."""
    from atlas.agents.methods import VISITORS, method_for
    from atlas.agents.runner import ready
    with session() as s:
        srcs = list(s.scalars(select(Source).order_by(Source.tier, Source.name)))
        stats = {sid: (n, last) for sid, n, last in s.execute(
            select(Signal.source_id, func.count(), func.max(Signal.published_at)).group_by(Signal.source_id)).all()}
    out = []
    for x in srcs:
        m = method_for(x)
        live = ready(x) and m in VISITORS
        why = ("watched live" if live else
               "Phase 2 (paid API or login)" if x.mvp_collect == "phase2" else
               "later phase" if x.mvp_collect == "later" else
               x.mvp_collect.replace("blocked:", "blocked · ") if x.mvp_collect.startswith("blocked") else
               "archive only (sitemap backfill)" if m == "sitemap" else "not reachable live")
        n, last = stats.get(x.source_id, (0, None))
        out.append({"id": x.source_id, "name": x.name, "platform": x.platform, "tier": x.tier, "lang": x.lang,
                    "method": m, "live": live, "status": why, "archived": n, "last_post": _iso(last),
                    "bias": x.bias_note})
    return out
