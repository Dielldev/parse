# Parse demo recordings

Scripted, repeatable screen recordings of every Parse tab (Ask, Watch, Trace, Signals, Sources, Agents, Workflow, Overview).

- `lib.py`    drives the running app with Playwright and records it (CDP screencast, native 1920x1080, visible cursor + click ripples)
- `demo.py`   one function per tab: the click-by-click script, with camera moves (zoom), captions and speed-ups
- `render.py` turns a recording into an mp4: smooth zoom/pan, captions, title card, fades
- `build.py`  renders the five main-tab clips into `out/main/` (standalone files, no title cards)

```bash
# the app must be running on :8765  (.venv/bin/uvicorn parse.web.app:app --port 8765)
.venv/bin/python video/demo/demo.py ask watch trace how agents_x agents_reddit agents_discord agents_news
.venv/bin/python video/demo/build.py                     # render everything in out/main/
```

Raw frames go to `$PARSE_DEMO_WORK` (default `/tmp/parse-demo`). Tweak a tab by editing its function in `demo.py`
(`r.zoom_on(selector, zoom)`, `r.caption(text, seconds, sub)`, `async with r.fast(3.0):` to speed up a wait) and re-record only that tab.
Notes: Ask/Trace use the Qwen engine (a few cents); Watch replays archived data (free); the Agents demo reads public Telegram
preview pages (read-only) and archives a few matching posts.

The Telegram clip (`05a`) is cut from a longer live-scout recording (`agents_telegram` in demo.py re-records it, but that scrapes Telegram).
`archive_v1/` holds the earlier long version (all 8 tabs, ~5 min); delete it if not needed.
