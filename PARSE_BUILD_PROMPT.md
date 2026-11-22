# Build prompt: Parse detection + validation pipeline (MVP)

> Paste everything below the line into Claude Code (or another coding agent), opened in this folder.

---

You are building the MVP of **Parse**, an OSINT early-warning system for Kosovo. The full brief is in `Atlas_Kosovo_Threat_Landscape.pdf` and the source registry is `parse_sources.csv`, both in this folder. **Read the whole PDF before writing any code.** It defines the threat labels (T1–T10), narrative codes (N1–N11), keyword seeds, the Signal/Event/Alert JSON schemas, the Threat Priority Score (TPS), the tracing algorithm and the guardrails. Follow it unless this prompt says otherwise.

## The core problem you are solving

A plain LLM that reads a post and returns a "confidence score" is not good enough. Its confidence is not calibrated and nothing can be audited. Parse must answer three separate questions, each in a measurable way:

1. **Detection: is this post threat-relevant?** Use a small fine-tuned multilingual classifier with calibrated probabilities, scored on a held-out test set. Do not use LLM self-reported confidence.
2. **Significance: is it big enough?** Use statistics: volume against that narrative's own baseline, independent-origin count, cross-platform spread and coordination signals.
3. **Validation: is it true?** Use evidence from independent sources in the registry, with a verdict decided by fixed rules. The LLM only extracts claims and judges whether evidence supports or contradicts them; it never decides truth from its own knowledge.

Truth and spread are independent axes. A false story spreading fast is a P1 information operation. The system must alert on it while marking it "Unverified" or "Debunked"; it must not wait for verification.

## Hard constraints

- **Budget: about $20 of Anthropic API credit in total.** Keep a spend ledger (`data/spend_ledger.csv`: timestamp, stage, model, input tokens, output tokens, USD). Before any paid run, print an estimated cost and **stop and ask me to approve it**. Never let the total pass $15 without my explicit approval.
- **Models:** `claude-sonnet-5-5` for teacher labeling (through the **Message Batches API**, 50% off) and for P1/P2 verification. `claude-haiku-5-5` for runtime escalations from the classifier. Use the official `anthropic` Python SDK and structured outputs (`output_config.format`) for every LLM call. Store each LLM output together with its prompt version.
- **Everything else must be free and local:** open-source models from Hugging Face, and free Colab/Kaggle GPUs for training.
- **Guardrails from Section 13 of the brief are code, not comments:**
  - Collect only from sources in the registry.
  - No logins, fake accounts or bypassing of access controls.
  - Respect robots.txt and rate limits.
  - Lawful protest, journalism and opposition politics are never threat labels on their own.
  - No ethnic profiling. Produce a bias report comparing alert rates for Albanian and Serbian content.
  - Attribution wording follows Section 10: "earliest observed source", "amplified by". Never "Serbia/Russia did X".
- Do not use the X/Twitter API (paid). For the MVP, collect from Telegram public previews (`https://t.me/s/<channel>`), news RSS feeds, and official sites. Mark X, Facebook and TikTok as Phase 2.

## Stack

Python 3.12, FastAPI, PostgreSQL + pgvector (via `docker-compose`), Playwright only where there is no RSS or static HTML, and `uv` for dependencies. Keep keywords and narrative seeds in `config/keywords.yaml` and model thresholds in `config/thresholds.yaml`, not in code. Write pytest tests for the scoring, verdict and significance logic.

## Build in phases. Stop at each ⛔ checkpoint and show me the results before continuing.

### Phase 0: Foundations
- Repo layout, `docker-compose.yml` (Postgres + pgvector), and DB migrations for the Source, Signal, Event and Alert tables, matching Section 9 of the brief.
- Import `parse_sources.csv` into the Source table. Add a `tier` column:
  - 0 = official/primary
  - 1 = established outlet
  - 2 = specialist OSINT
  - 3 = partisan or unverified

  Propose a tier for each row and add a `bias_note` field (for example, the CSV notes Kosovo Online is Serbian-leaning). ⛔ Show me the tier table for approval.
- An evidence store: save each raw page or post (HTML plus text) with its SHA-256 hash. Screenshots are optional for the MVP.

### Phase 1: Data collection and historical backfill
- Collectors: Telegram public-preview scraper (with pagination back in time through `?before=<post_id>`), RSS/news collector, and official-site collector. Each one emits Signal records.
- Normaliser: language detection (sq, sr-Latn, sr-Cyrl, ru, en), Serbian Cyrillic→Latin transliteration, translation to English (with a free model such as NLLB or opus-mt), OCR on images (Tesseract), and a perceptual hash (pHash) for each image.
- **Backfill these windows for training and back-testing:**
  - Gazimestan / Vidovdan: 20 Jun – 5 Jul 2026
  - Ibar-Lepenac canal blast: 25 Nov – 6 Dec 2024
  - Banjska attack: 20 Sep – 5 Oct 2023
  - Dec 2025 election period: 1–31 Dec 2025
  - At least 4 "quiet" windows with no major incident, so the model learns what normal looks like
- ⛔ Report how many signals were collected per window, language and source, and flag gaps.

### Phase 2: Teacher labeling and the gold set
- Write a labeling prompt (stored in `prompts/label-v1.md`) that outputs, as structured JSON: `labels` (T1–T10, multi-label, can be empty), `narratives` (N1–N11), `offline_intent` (bool plus the text span), `places`, `orgs`, and `is_threat_relevant` (bool). Include the exact label definitions from Section 3 and the rights rule (protest, journalism and opposition are not threats).
- Run a 50-post pilot first, then ⛔ show me the cost and quality. After approval, label about 3,000–5,000 posts through the Batch API.
- Build a minimal labeling UI (a FastAPI page) where team members review and correct the labels. Target **500–800 human-corrected posts** as the gold set. Record who labeled each one.
- **Split by event or time window, never randomly**, so the test set contains incidents the model has never seen. Suggested split: train on Banjska, the election and the quiet windows; validate on the canal blast; hold out Gazimestan 2026 as the test set and back-test. Explain your split.

### Phase 3: The specific classifier
- A Colab/Kaggle notebook (`notebooks/train_classifier.ipynb`) that fine-tunes `xlm-roberta-base` and `microsoft/mdeberta-v3-base` as multi-label classifiers on original-language text (also try the English translation, and report which works better).
- Apply **temperature scaling** on the validation set so probabilities are calibrated.
- Report on the **test set**: precision, recall and F1 per label and per language; macro-F1; a calibration (reliability) plot plus expected calibration error (ECE); and a confusion analysis of the worst errors.
- **Baseline comparison:** run the "naive approach" (Haiku zero-shot with a self-reported confidence score) on the same test set and compare it with the fine-tuned model on F1, calibration and cost per 1,000 posts.
- **Cascade:** the classifier handles a post on its own when its calibrated probability is confident. Posts in the uncertain band (start at 0.35–0.75 and tune it on the validation set) go to Haiku. Report what share of posts escalates and the accuracy of the cascade as a whole.
- Export the model to run locally on CPU (ONNX or a plain `transformers` pipeline). ⛔ Show me the metrics report.

### Phase 4: Clustering and significance
- Group signals into Events using multilingual embeddings (`intfloat/multilingual-e5-base` or LaBSE, stored in pgvector) plus image pHash matches, inside a rolling time window.
- Tracer (Section 10 of the brief): build the edges (forward, quote, copy, link, translate) and collapse signals into **origin groups**, so reposts of one original count once.
- Significance features per Event, each stored with a plain-language explanation:
  - **velocity_z**: posts in the last 60 minutes against a baseline for the same narrative/keyword cluster and the same hour of the week, as a z-score (Poisson-based when counts are low)
  - **independent_origins**: number of distinct origin groups
  - **cross_platform**: which platforms have it, and the time between the first and the second platform
  - **coordination**: near-duplicate share within 10 minutes, share of new accounts, fan-out
  - **proximity**: north Kosovo, crossings or critical infrastructure named, or a trigger-calendar window
- Feed these into the TPS formula from Section 8, including the tripwires and P1–P4 bands. The explanation must say which factors drove the score.

### Phase 5: Validation (the Verifier)
Run only on P1/P2 candidates, to save credits.

1. **Claim extraction:** turn the event's top signals into atomic who/what/where/when claims.
2. **Evidence retrieval:** search the local signal store and live-fetch Tier 0–1 sources (official sites, established outlets) for the same entities, places and time window.
3. **Independence:** group evidence by origin group. Two outlets citing the same Telegram post count as one source.
4. **Stance:** for each claim and evidence pair, decide supports / contradicts / unrelated. Try `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` first (free) and use Sonnet only when the NLI model is uncertain.
5. **Media checks:** match each image's pHash against everything stored earlier (to catch recycled images), and record EXIF data if present.
6. **Verdict by deterministic code, not the LLM:**
   - CONFIRMED: at least 1 Tier-0 item supports and none contradicts
   - CORROBORATED: at least 2 distinct origin groups at tier ≤ 2 support
   - DISPUTED: both supporting and contradicting evidence exist
   - DEBUNKED: a Tier-0 source contradicts, or the media matches an earlier unrelated event
   - UNVERIFIED: anything else

   Each verdict lists its evidence ids and `suggested_checks` for what is missing.

The Verifier's LLM system prompt must say: it never judges truth from its own knowledge; it only labels the evidence it was given, with exact spans and ids; and it follows the attribution wording rule.

### Phase 6: Alerts, back-test and report
- Brief Writer: a 3–5 sentence alert with `[n]` citations, plus `what_we_know`, `what_we_dont_know` and `suggested_checks` (Alert schema, Section 9).
- **Back-test:** replay the held-out Gazimestan 2026 window in time order, as if live. Report when Parse would have raised each alert, compared with the timestamp of the first mainstream news report, for detection lead time. Check the acceptance criteria in Section 1 of the brief: median lead time ≤ 60 min, origin tracing on P1/P2, and 100% of alerts with archived evidence.
- A simple dashboard page: alert queue → event → spread graph → evidence with verdict.
- Write `REPORT.md` for our mentor with: the architecture diagram, the gold-set and split design, the classifier against the naive LLM baseline (table + calibration plot), the back-test timeline, the bias report, total API spend, and known limitations. Be honest about failures.

## Working style
- Before each phase, give me a short plan. After each phase, give me what you built, how you tested it, and what is not done.
- Prefer simple, working code over clever code. Don't add features I didn't ask for.
- If a source blocks scraping or a model doesn't fit in memory, tell me and propose an alternative. Don't silently work around it.
- Never commit API keys. Read `ANTHROPIC_API_KEY` from the environment.

Start with Phase 0: read the PDF and the CSV, then show me your plan and the proposed source tiers.
