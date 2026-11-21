"""Phase 1 checkpoint report: signals per window, language and source, plus gaps."""
from __future__ import annotations

from collections import defaultdict

import yaml
from sqlalchemy import func, select

from atlas.db import session
from atlas.models import Signal, Source
from atlas.settings import CONFIG_DIR, DATA_DIR


def build() -> str:
    windows = yaml.safe_load((CONFIG_DIR / "windows.yaml").read_text())["windows"]
    with session() as s:
        rows = s.execute(select(Signal.window, Signal.lang, Signal.source_id, func.count())
                         .where(Signal.window.is_not(None))
                         .group_by(Signal.window, Signal.lang, Signal.source_id)).all()
        srcs = {x.source_id: x for x in s.scalars(select(Source))}
    by_w = defaultdict(int)
    by_wl = defaultdict(lambda: defaultdict(int))
    by_src = defaultdict(lambda: defaultdict(int))
    for w, lang, sid, n in rows:
        by_w[w] += n
        by_wl[w][lang or "unknown"] += n
        by_src[sid][w] += n
    langs = ["sq", "sr-Latn", "sr-Cyrl", "ru", "en", "unknown"]
    other = sorted({l for d in by_wl.values() for l in d} - set(langs))
    cols = langs + other
    out = ["# Phase 1 coverage report", "", "## Signals per window and language", "",
           "| window | split | total | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 3)]
    for w, meta in windows.items():
        out.append(f"| {w} | {meta['split']} | {by_w.get(w, 0)} | " +
                   " | ".join(str(by_wl[w].get(c, 0)) for c in cols) + " |")
    out.append(f"| **all** | | **{sum(by_w.values())}** | " +
               " | ".join(str(sum(by_wl[w].get(c, 0) for w in windows)) for c in cols) + " |")
    out += ["", "## Signals per source", "", "| source | tier | lang | total | " +
            " | ".join(windows) + " |", "|" + "---|" * (len(windows) + 4)]
    for sid in sorted(by_src, key=lambda k: -sum(by_src[k].values())):
        src = srcs[sid]
        out.append(f"| {src.name} | {src.tier} | {src.lang} | {sum(by_src[sid].values())} | " +
                   " | ".join(str(by_src[sid].get(w, 0)) for w in windows) + " |")
    zero = [x for x in srcs.values() if x.mvp_collect == "yes" and x.status == "verified"
            and x.platform in ("news", "official", "mirror") and x.source_id not in by_src]
    out += ["", "## Gaps", "", f"Verified sources with zero backfilled signals ({len(zero)}):", ""]
    out += [f"- {x.name} (`{x.source_id}`, tier {x.tier}): {x.check_note}" for x in sorted(zero, key=lambda x: x.name)]
    not_collected = [x for x in srcs.values() if x.mvp_collect != "yes"]
    out += ["", f"Sources not collected in the MVP ({len(not_collected)}):", ""]
    reasons = defaultdict(list)
    for x in not_collected:
        reasons[x.mvp_collect].append(x.name)
    out += [f"- **{k}** ({len(v)}): {', '.join(sorted(v))}" for k, v in sorted(reasons.items())]
    thin = [w for w in windows if by_w.get(w, 0) < 300]
    if thin:
        out += ["", "Windows with fewer than 300 signals: " + ", ".join(thin)]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = build()
    (DATA_DIR / "coverage_report.md").write_text(text)
    print(text)
