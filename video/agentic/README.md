# Parse · the agentic loop (30 s product film)

A 30-second, 1920×1080, 60 fps film about the agentic loop: **Agents → Signals → Ask**. It is not a page-by-page
tour. Each beat shows the system doing the work, and every frame, number, title and URL comes from real runs of Parse.

Output: `video/out/parse-agentic-loop.mp4` (H.264, AAC 48 kHz, −14 LUFS).

## What is on screen, and where it comes from

| Time | Beat | Source of truth |
|---|---|---|
| 0–2 s | "Dashboards wait. Agents don't." The word *Agents* lands on the agent's own badge. | — |
| 2–6 s | **Browser scout**: a real Chromium session on Telegram (`@balkanspectator`, `@balkanar`). It types "Kosovo", reads, highlights and archives posts. Speed-ramped ×2 → ×25, with the speed shown on screen. | `data/scout.json` + `footage/used/*.jpg`: the scout's own screencast frames and event log (run `run_01M80HAZ…`: 34 read, 33 matched, 15 archived) |
| 6–10 s | **46 field agents**: a waterfall built from the real event log. 8 run in parallel over site search APIs and RSS. Real GET URLs, 13 new items, 6 problems (HTTP 403, unreachable, too slow). | `data/agents.json` (run `run_01M80HG7…`, 17.3 s) |
| 10–16 s | **Signals**: the canal window (29 Nov 2024) replayed in time order. Qwen3-8B labels each post (T3/T4/T6, N-codes, places). Routine politics are marked "not a threat" (the rights rule). Four posts in two scripts group into one story. TPS factors give a score of 53.5, and a tripwire forces P1. | `data/signals.json` (teacher-label outputs) + the canal replay (`video/src/data/watch_state.json`: 140 → 138 → 95 → 9 → 1, P1 at 73 min) |
| 16–17.5 s | **P1 in 73 min.** The alert is pinned on the product's own Kosovo map at the Ibar–Lepenac canal. | Same replay; map from the Ask page (`data/kmap.svg.html`) |
| 17.5–25 s | **Ask**: "What happened at the Ibar-Lepenac canal?" with field agents on. Eleven real steps with real timings: agents 17.3 s, search 486 of 33,285 signals, 8/8 SHA-256 intact, Qwen3-8B labels T3×8. | `data/ask.json` (streamed NDJSON from `/api/ask`) |
| 25–28 s | The cited answer: headline, findings and 8 citations with tier, date, language and hash. | Same |
| 28–30 s | The answer folds into the PARSE mark. | — |

Honesty labels are part of the picture. The bottom readout says LIVE RUN, BACK-TEST or LIVE QUERY with the real time,
and the speed of every time-lapse is printed on screen. "No model" appears on every Ask step where no model ran.

## Rebuild it

The app must be running (`uv run uvicorn parse.web.app:app --port 8765`) with its database.

```bash
.venv/bin/python video/agentic/tools/capture.py scout     # real browser scout, every frame (headless)
.venv/bin/python video/agentic/tools/capture.py label     # Qwen labeller on the 8 cited items (~$0.003, Featherless)
.venv/bin/python video/agentic/tools/capture.py ask       # Ask with field agents, plus the agents' event log
.venv/bin/python video/agentic/tools/capture.py signals   # labelled posts for the canal window
.venv/bin/python video/agentic/tools/capture.py map       # the product's Kosovo map
.venv/bin/python video/agentic/tools/prep.py              # pack data/film.json + pick footage frames for the ramp
```

Review, then render:

```bash
.venv/bin/python video/tools/stills.py /tmp/stills --src video/agentic --every 0.5      # one still per beat + contact sheet
.venv/bin/python video/tools/render.py --src video/agentic --out video/out/parse-agentic-loop.mp4
.venv/bin/python video/tools/render.py --src video/agentic --draft                      # 30 fps, no blur, quick look
```

## How it is built

- `index.html` + `film.css` + `lib.js` + `film.js`: a deterministic HTML composition. `window.seek(t)` writes every
  style from `t`, with no timers, CSS animations or carried state, so any frame renders identically. It follows the
  prompt-motion.com approach: a 120 BPM beat grid, every shot made out of the previous one (the camera is the
  transition), closed-form easing, and no glows, flares, shake or crossfades.
- `audio.js`: the soundtrack is synthesised in an `OfflineAudioContext` (D minor, 120 BPM). Every UI sound (keystroke,
  match, kept item, agent request, label, P1, workflow step) comes from the same cue list as the picture.
- `video/tools/render.py`: headless Chromium (Playwright) captures each frame, 3 samples per frame give motion blur,
  ffmpeg encodes, and the sound is mastered with two-pass loudnorm.

Dependencies already in this repo's `.venv`: Playwright + Chromium, numpy, Pillow. System: ffmpeg. Fonts (Inter Tight,
IBM Plex Mono) load from Google Fonts at render time, as the product does.

`footage/` holds the raw screencast (`scout/`, about 600 MB) and the frames the film uses (`used/`, about 150 MB). It is
git-ignored.
