# SDMS local AI service

Everything here runs on the machine: no cloud call, no API key for any third party. After the image is built (it bakes in
the embedding model, `HF_HUB_OFFLINE=1`) the only network traffic is to your own Ollama on `host.docker.internal:11434`.

```
upload    ─► /ai/process ─► OCR ─► entities ─► classifier (+ title prior) ─► embedding ─► result returned to the API
on demand ─► /ai/summarize, /ai/summarize-case ─► Ollama `sentinel-legal` ─► grounding guard ─► summary
```
The service keeps no state and stores no documents.

| Piece | What it is | Trained/fine-tuned by us? |
|---|---|---|
| OCR (`app/ocr.py`) | PyMuPDF text layer when present, otherwise Tesseract 5 (English, Hindi, Tamil), page and time budget | No |
| Entities (`app/entities.py`) | Regular expressions: persons, places, dates, IPC/BNS/CrPC/BNSS/NDPS/POCSO/IT Act sections, amounts, phones, vehicle numbers, case numbers; Devanagari and Tamil numerals | No (rules, 6 unit tests) |
| **Classifier** (`app/classifier.py`) | `distilbert-base-multilingual-cased` **fine-tuned** on 13 document types, temperature-calibrated | **Yes** — `training/train_classifier.py` |
| Title prior (`app/titles.py`) | If a class's own title ("FIRST INFORMATION REPORT", "CHARGE SHEET", …) is in the first 240 characters, its score gets a bonus; if that disagrees with the model the document is flagged `needs_review` | Rule; the bonus (8.0) was picked on a grid |
| Embeddings (`app/embedder.py`) | `paraphrase-multilingual-MiniLM-L12-v2` (384-d), up to 4 × 160-word windows averaged | **No** — off the shelf |
| LLM (`app/llm.py`, `Modelfile`) | `qwen2.5:3b` in Ollama as `sentinel-legal` (system prompt + sampling parameters) | **No** — this is prompt customisation, *not* fine-tuning |
| Grounding guard (`app/grounding.py`) | Drops any summary sentence containing a section, date, amount, phone, vehicle or case number that is not in the source | Rule (5 unit tests) |

So the honest claim is: **one model is fine-tuned (the classifier); the LLM and the embedder are used as published.**

## How good is the classifier?

**Deployed model: round 2** (round 1 kept as a backup at `models/classifier_r1`). Round 2 adds 312 LLM-written documents to
training (each repeated 4×, re-augmented every time — see "Training offline" below). Measured on four sets it never
trained on, with the deployed settings (title prior 8.0). "Unflagged error" = wrong **and** not sent to a human
(`needs_review` false) — the number that matters for an officer who trusts the label without a second look.

| Test set | n | Accuracy (round 1 → round 2) | Sent to review | Wrong, unflagged (r1 → r2) | Wrong, confident ≥0.9 (r1 → r2) |
|---|---|---|---|---|---|
| Held-out **layouts** (synthetic, same generator) | 390 | 90.5 % → **99.2 %** | 15 % | 4.6 % → 0.5 % | 0.5 % → 0.3 % |
| Same, with OCR-style noise | 390 | 66.9 % → **80.5 %** | 20 % | 21.8 % → 12.6 % | 13.6 % → 8.7 % |
| Written by the LLM (same generator as some training rows — see caveat) | 104 | 55.8 % → **85.6 %** | 10 % | 33.7 % → 9.6 % | 26.9 % → 6.7 % |
| Hand-written by us, never used in training | 29 | 65.5 % → **93.1 %** | 10 % | 20.7 % → 3.4 % | 24.1 % → 3.4 % |

Every number improved, on every set, in this round. The **hand-written set is the strongest signal**: it was never touched
by training (not templated, not LLM-generated, not augmented), so its +27.6-point jump is the most trustworthy evidence that
round 2 generalises better, not just that it memorised more.

**Caveat on the LLM-written number:** `llm_test.jsonl` (this test set) and `llm_train.jsonl` (312 rows added to training)
are different documents, but the *same generator and prompt style* (`qwen2.5:3b`, `training/llm_generate.py`). Part of that
+29.8-point jump is genuine improvement and part is the model becoming familiar with that one generator's phrasing — real
documents won't look like either. Weight the noisy and hand-written columns more heavily than this one.

The "99 %" in `val_seen` (not shown above) is the *same templates with new names* — memorisation, not generalisation, and
should never be quoted on its own.

**What this means:** training data is still synthetic templates plus one LLM's writing — no real police document has been
in the loop. Round 2 is a large, verified improvement on every test we have, but "real-world accuracy" remains unmeasured.
Treat the label as a *suggestion*: the UI shows a review badge and lets the officer change the type. A correction is
recorded in MongoDB (`ai_feedback`: predicted type, corrected type, document id — **no text**), so it can be counted but
**cannot yet be turned into training data**; there is no exporter.

## Training offline (the whole loop runs on this machine)

Nothing here needs the internet once two things are on disk: the training venv (`ai/.venv-train`, torch 2.6 + CUDA 12.4) and
the base model in the Hugging Face cache (`%USERPROFILE%\.cache\huggingface\hub\models--distilbert-base-multilingual-cased`,
~520 MB — copy that folder to another machine to train there). Setting the two `*_OFFLINE` variables makes any missing file an
immediate error instead of a network attempt.

Each round trains into a **new** folder so the deployed model stays untouched until you have compared the two. This is what
produced round 2 (took 266 s / 5 epochs on the RTX 3050); the same recipe applies to a future round 3, pointed at
`models\classifier_r3` and whatever new `--extra` data you have:

```powershell
cd ai
$env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"
ollama stop sentinel-legal            # free the 4 GB GPU; do not ask for summaries while training

# 1. train (about 5 min on the RTX 3050); prints loss / val accuracy per epoch, then the held-out results
.venv-train\Scripts\python -u -m training.train_classifier --data data --out models\classifier_r3 --epochs 5 --extra data\llm_train.jsonl --extra-repeat 4

# 2. compare with the deployed model on the same held-out sets: prints the title-prior grid, --write stores the bonus-8 row in metrics.json
.venv-train\Scripts\python -m training.evaluate --model models\classifier_r3 --data data --bonus 0,4,8,12 --write 8

# 3. only if it is better: keep the deployed model as a backup, swap, rebuild the service
Rename-Item models\classifier classifier_r2_backup ; Rename-Item models\classifier_r3 classifier
cd .. ; docker compose build ai ; docker compose up -d ai
curl.exe http://127.0.0.1:9000/ai/health          # shows the model's measured_accuracy from metrics.json
```

`docker compose build ai` only replaces the last layer (the model files), so it should not need the internet; if Docker
complains about reaching Docker Hub, run it once while online. Run `--write` **before** the rebuild, because the service
reports the numbers in `metrics.json`. If the new round is worse, delete its folder — nothing else changed.

**Adding your own labelled documents:** one JSON object per line, `{"text": "...", "label": "<one of the 13 types>", "lang": "en|hi|ta"}`
(see `data/llm_train.jsonl`), passed with `--extra a.jsonl,b.jsonl`. More LLM-written ones:
`python -m training.llm_generate --out data\llm_train2.jsonl --per-class 24 --seed 303` (needs Ollama; labels come from the
prompt, so some are wrong; do not run it during training, both want the GPU). The held-out sets `llm_test`,
`handwritten_test` and `val_unseen*` must **not** be added to training, or the accuracy numbers stop meaning anything.
**Real, redacted documents (once available) would matter more than any amount of extra synthetic or LLM-written data.**

`--write N` stores that bonus's results in `metrics.json`. On round 2, a bonus of 12 scores a little higher than 8 on the
noisy and LLM-written sets but a little lower on hand-written (see `hybrid_grid` in `models/classifier/metrics.json` for the
full table); 8 is kept deployed rather than picked from the same sets being reported, which would flatter the numbers.
Change it with `TITLE_BONUS` only once you have a fresh, untouched test set.

Training environment: `ai/.venv-train` (torch 2.6 + CUDA 12.4), an RTX 3050 4 GB. The embedding matrix is frozen so it fits.

## Summaries and the grounding guard

`sentinel-legal` hallucinated once during development (it wrote "Section 324 IPC … assault … woman" for a DNA report). The
prompt now says to mention a date/amount/section only if written, and `grounding.py` removes any sentence with an
unsupported specific. That catches invented *numbers*; it cannot catch a soft claim ("the accused appeared cooperative").
Summaries are therefore labelled as AI-written in the UI and are on demand, never automatic. A summary takes a few
seconds once Ollama has the model loaded; the first one after it unloads is slower.

Setup once (Ollama must be installed and running on the host):

```powershell
ollama pull qwen2.5:3b
ollama create sentinel-legal -f ai/Modelfile
```

## Service endpoints (all except `/ai/health` need `X-API-Key`)

`GET /ai/health` · `POST /ai/process` (file → text, language, entities, type, confidence, embedding) · `POST /ai/embed` ·
`POST /ai/summarize` · `POST /ai/summarize-case`. The exact contract is in [`../docs/AI_CONTRACT.md`](../docs/AI_CONTRACT.md).
If the service is configured but unreachable, uploads still succeed: the document is encrypted, hashed and anchored, but
stays unclassified, un-OCR-ed and un-indexed (its provider shows `unavailable (...)`). Only when no service URL is
configured at all does the backend use its small built-in rule engine.

## Data

`data/` holds the generated sets (`train`, `val_seen`, `val_unseen`, `val_unseen_noisy`) and the independent ones
(`llm_test`, `llm_train`, `handwritten_test`). `training/corpus*.py` are the generators; `training/llm_generate.py` asked the
local `qwen2.5:3b` to write extra documents; `training/handwritten.py` is the 29 hand-written ones.

## Known weaknesses

* Real-world classification accuracy is unknown and probably nearer the last two rows above than the first.
* The OCR path was verified on a scanned PDF and a photographed page, both English. Hindi/Tamil OCR has not been tried on
  real scanned documents (the language packs are installed; accuracy is unmeasured).
* Handwriting is not OCR-ed reliably (Tesseract is not a handwriting engine).
* Semantic search uses one averaged vector per document with a 0.25 cosine cutoff, so short, specific queries against a long
  document can return nothing; keyword search covers exact terms.
* Embeddings are stored unencrypted (they leak topic, not text), unlike the OCR text and entities.
