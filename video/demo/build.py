"""Render the five main-tab clips (Agents has one clip per platform) to video/demo/out/main/.

  .venv/bin/python video/demo/build.py              # all
  .venv/bin/python video/demo/build.py ask trace    # just these (by output name fragment)

Each clip is standalone: no title card, short fade in/out, captions burned in.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import render_clip  # noqa: E402

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get("PARSE_DEMO_WORK", "/tmp/parse-demo"))
OUT = ROOT / "out" / "main"

# (output name, recorded clip, trim_start s, trim_end s)
CLIPS = [
    ("01_ask", "ask", 0.4, 0),
    ("02_watch", "watch", 0.4, 1.5),
    ("03_trace", "trace", 0.4, 1.0),
    ("04_workflow", "how", 0, 0),
    ("05a_agents_telegram", "agents_telegram", 48, 26.7),
    ("05b_agents_x", "agents_x", 0, 0),
    ("05c_agents_reddit", "agents_reddit", 0, 0),
    ("05d_agents_discord", "agents_discord", 0, 0),
    ("05e_agents_news", "agents_news", 0, 0),
]


def main():
    want = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    for out, clip, ts, te in CLIPS:
        if want and not any(w in out for w in want):
            continue
        if not (WORK / clip / "timeline.json").exists():
            print("skip (not recorded):", clip)
            continue
        render_clip(WORK, clip, OUT / f"{out}.mp4", trim_start=ts, trim_end=te)


if __name__ == "__main__":
    main()
