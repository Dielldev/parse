# Atlas: Watch + Tracer (guide for the demo video)

## The problem (from the brief)

When a threat-relevant story about Kosovo starts spreading online, KSF analysts find out hours or days late and
**cannot see where it started or who is pushing it**. Posts are scattered across news sites, official sites,
Telegram and social media, in Albanian, Serbian (Latin and Cyrillic), Russian and English. Analysts watch by hand,
there is no archive, and there is no record of how a story spread.

## What we built

**1. Watch (`/watch`): the automation.** Atlas watches the accounts for you. Every cycle it:

| Step | What happens |
|---|---|
| 01 Collect | Field agents visit every live account in the registry (46 news, official and mirror sites; Telegram and X are later phases) and archive what is new, with a SHA-256 hash of each page. |
| 02 Filter | Keeps the posts about Kosovo. |
| 03 Group | Joins each post to an open story (same wording, close meaning, or the same names and places in any language), or opens a new story. |
| 04 Trace | Runs the Tracer on every story that grew (2+ posts from 2+ accounts). |
| 05 Alert | A story that reaches priority P1/P2 raises an alert, with how many minutes after the first post. |

It runs in two modes:
- **Live accounts**: real posts, right now, one round every 5 minutes.
- **Replay a window**: an archived incident is released in time order as if it were live. This is the back-test the
  brief asks for: *"would Atlas have caught it, and how early?"* The Tracer only sees posts published up to the
  replay clock, so it cannot cheat by looking ahead.

**2. Tracer (`/trace`): where did this story start?** Give it one post, a link, a **screenshot** (for example an
Instagram or Telegram post with text in it; Atlas reads it with OCR) or pasted text. It follows Section 10 of the
brief:

1. **Seed**: what we trace, plus the distinctive words (names, places) to search for.
2. **Expand backwards**: finds earlier and later posts about the same thing: shared words, links between posts, the same image, close meaning **across languages** (local embeddings, free).
3. **Build the graph**: typed edges from the earlier post to the later one: *forward, quote, copy, link, translate*. Reposts of one original form one **origin group**.
4. **Pick the origin**: the earliest post with no parent = **earliest observed source**, with a confidence score and every reason it was lowered.
5. **Find the amplifiers**: which outlets passed the story on to others, and how often they did so in earlier traces (how Atlas learns the network).
6. **Discover new sources**: unknown sites and channels the story links to go into a queue for a human to approve.
7. **Link to the real world**: official (Tier 0) statements and trigger-calendar dates (anniversaries).
8. **Score significance**: speed against baseline, independent origins, platforms, coordination, sensitive places, and tripwires → **Threat Priority Score, P1 to P4**.
9. **Check the claim**: one post per independent origin group; a model only says supports / contradicts / unrelated, and **fixed rules** decide the verdict (CONFIRMED, CORROBORATED, DISPUTED, DEBUNKED, UNVERIFIED).
10. **Write the brief**: what it is about, where it started, who carried it, what we know, what we don't know, and what to check next.

Attribution rule, enforced in code: Atlas says *"earliest observed source"* and *"amplified by"*, never
*"Serbia/Russia did X"*. A model-written brief that breaks the rule is thrown away.

## Results worth showing

- **Ibar-Lepenac canal blast (29 Nov 2024).** Tracing from the Albanian report (Reporteri) and from the Serbian
  report (KoSSev) both lead to the **same origin: KoSSev, 29 Nov 2024 19:05 UTC**, with Insajderi 16 minutes later.
  The graph holds about 75 posts in sq / sr-Latn / sr-Cyrl / en, with translate edges between languages.
- **Replay of the canal window with Qwen on:** the watcher raised a **P1 alert 73 minutes after the first post**, and
  the dashboard shows the first Tier 0-1 report next to it (the lead-time back-test).
- Every trace says whether it passes the MVP test (*earliest known post + at least 2 spread steps*).

## Demo script (about 3 minutes)

1. Open `/watch` → **Replay a window** → `canal_2024_11`, start `29.11.2024 12:00`, 3 hours per tick.
   Switch on **Label & check claims with Qwen** (billed, a few cents) so alerts can fire → **Start watching**.
2. Show the pipeline strip lighting up (Collect → Filter → Group → Trace → Alert), the incoming-posts feed and
   the activity log.
3. When the canal story appears with **ALERT P1**, click **Show tracing steps**, then **Open full trace →**.
4. On the trace page: the brief, the **earliest observed source** with confidence, the **spread graph** (hover a node
   to light up its path back to the origin), amplifiers, claim check, new sources.
5. On `/trace`, open the **Screenshot** tab and paste a screenshot of a post to show tracing from an image.
6. Switch `/watch` to **Live accounts** to show it working on today's posts.

## Run it

```bash
docker compose up -d                       # Postgres + pgvector
uv run alembic upgrade head                # adds event.seed / event.trace (migration 0004)
uv run uvicorn atlas.web.app:app --port 8000
```

Then open http://localhost:8000/watch and http://localhost:8000/trace. From the command line:
`uv run atlas trace sig_...` (or a link, or a piece of text).

Model calls (claim checks, labels, brief) are optional and billed on Featherless (`FEATHERLESS_API_KEY` in `.env`).
Everything else, including search, embeddings, graph, origin and score, runs locally for free.

## Honest limits

- Atlas only sees its registry: X, Facebook and TikTok are Phase 2, so the "earliest observed" source may not be
  the true first post. The confidence score says so.
- Edges are inferred from wording, links, images and meaning. They show likely paths, not proof.
- Some outlets give a date without a time; their order within that day is unknown and is shown faded.
- Without the Qwen engine, posts have no threat labels, so tripwires cannot fire and stories stay at P3/P4.
- Story grouping uses thresholds tuned on the canal window (`config/thresholds.yaml`, `watch:` and `tracer:`).
