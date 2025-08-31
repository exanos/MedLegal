

# MedLegal – Local Claim Dossier Pipeline (DocAI + Gemini)

**with demo web UI (Flask)**

> Local Python pipeline for ingesting medical-legal PDFs, page-classifying them with **Google Document AI**, extracting full text, building a coherent **case** with **Gemini 2.5 Pro**, assigning **severity multipliers**, computing a **confidence** score, and emitting a **human-readable report** — all orchestrated via **FastAPI**.
> A separate **Flask** app (this repo’s `server.py`) provides a tiny web front-end that drives the FastAPI pipeline and renders the Markdown report in the browser.
> **Only** Document AI and Gemini calls use the cloud; everything else is local.

---

## Quickstart

```bash
# 0) Python 3.10+ virtualenv recommended
pip install -r requirements.txt

# 1) Create .env and verify all IDs/keys (see “Environment (.env)” below)
#    Make sure your ADC JSON exists and is accessible.

# 2) Start the FastAPI backend (the pipeline API)
uvicorn api.app:app --host 127.0.0.1 --port 8010 --reload

# 3) (Optional) Start the Flask demo UI (the browser app)
#    The UI will call the FastAPI server to run the full pipeline.
python server.py  # serves on http://127.0.0.1:5000
```

Open `http://127.0.0.1:5000` → upload a PDF → the UI hits FastAPI, runs the pipeline, and renders a report.

---

## Environment (.env)

```ini
# --- GCP / ADC ---
GOOGLE_APPLICATION_CREDENTIALS=c:\Users\<YOU>\AppData\Roaming\gcloud\legacy_credentials\<email>\adc.json
GCP_PROJECT_ID=75863170649
DOC_LOCATION=us

# --- Document AI processor IDs ---
DOC_AI_CLASSIFIER_ID=b9f4e6d27ae02eb3
DOC_AI_CLASSIFIER_VERSION_ID=c93ca7c3f2691d94   # optional; if set, uses this specific version
DOC_AI_LAYOUT_ID=811326a79660488
DOC_AI_OCR_ID=8dcb2b942361503
DOC_AI_FORM_ID=64703170cd6ee995

# --- Gemini ---
GEMINI_API_KEY=YOUR_GEMINI_KEY

# --- Local knobs ---
MAX_PAGES_PER_PDF=30
MEDLEGAL_SAMPLES_DIR=samples

# --- (Optional) Flask → FastAPI base URL override
MEDLEGAL_API_BASE=http://127.0.0.1:8010
```

> **Windows tip:** If ADC fails, double-check the path and that the service account has DocAI access.

---

## Repo Layout (high level)

```
medlegal/
│── api/app.py                    # FastAPI: /ingest, /adjudicate, /report.md, /search
│── config.py                     # Env + ClaimPaths (all original helpers preserved)
│── main.py                       # Optional CLI runner (step-by-step)
│
│── preprocess/
│   ├── splitter.py               # Split PDFs into ≤30-page chunks + single pages
│   ├── classifier.py             # Per-page classification → category buckets
│   ├── collect_text.py           # Build ALL.txt + manifest + citations
│   └── _docai_client.py          # Raw DocAI HTTP client helpers
│
│── storage/
│   ├── index.py                  # Chunk ALL.txt → chunks.jsonl, build SQLite FTS index
│   └── search.py                 # Search interface over the FTS DB
│
│── llm/
│   ├── case_builder.py           # Gemini Pro → case + ≥15 flags (with signed scores)
│   ├── severity.py               # Gemini Pro → multipliers per flag (JSON-only, robust)
│   └── scorer.py                 # Combine scores * multipliers, compute confidence
│
│── reports/report_generator.py   # Markdown report (exec summary + full flag matrix)
│── utils/io.py                   # UTF-8 safe read/write
│
│── samples/
│   ├── input_docs/<claim_id>/    # Uploaded originals
│   └── processed/<claim_id>/     # Pipeline outputs
│
│── server.py                     # Flask demo UI (browser)
└── static/
    ├── index.html                # Simple UI
    ├── app.js                    # Calls Flask /upload → FastAPI
    └── processing.gif            # Spinner
```

---

## Pipeline (what happens under the hood)

1. **Split**

   * Splits each PDF into ≤`MAX_PAGES_PER_PDF` chunks **and** 1-page PDFs (for per-page classification).
   * Writes → `samples/processed/<claim>/01_pages`.

2. **Classify**

   * Per-page call to **DocAI Classifier** (parallel).
   * Writes raw JSON next to each page and buckets copies into:
     `samples/processed/<claim>/03_classified_pages/<Category>/*.pdf`.

3. **Collect Text**

   * Prefers classifier’s raw `text`; falls back to DocAI OCR per page if missing.
   * Writes:

     * `07_text/ALL.txt` (full dossier, page headers like `=== Category#Page :: filename ===`)
     * `07_text/manifest.json`
     * `07_text/citations.json`

4. **(Optional) Index & Search**

   * Breaks dossier into chunks → `07_text/chunks.jsonl` and builds SQLite FTS → `index/index.db`.
   * `GET /claims/{id}/search?q=...` queries FTS.

5. **Case Builder (Gemini 2.5 Pro)**

   * Input = `ALL.txt`.
   * Output = `08_reports/case.json` with `case{...}` and **≥15 flags** (each: id, title, direction, score in \[-2..2], details, citations).

6. **Severity (Gemini 2.5 Pro)**

   * Sees **case** + **flags (without numeric scores)**.
   * Returns `{ "F#": { "multiplier": 0.5..3.0, "reason": "…" }, ... }` → `08_reports/severity.json`.
   * Also writes `severity_raw.txt` for debugging. (If you ever see truncation, lower batch size / max tokens in `severity.py`.)

7. **Score (local)**

   * Computes weighted = `score × multiplier` per flag; aggregates a **confidence** in \[0..1].
   * Writes `08_reports/scoring.json`.

8. **Report (local)**

   * Human-readable Markdown at `08_reports/<claim>_report.md` with exec summary, case, top supporting/contradictory points, and **full flag matrix**.

---

## FastAPI – the backend API

Base: `http://127.0.0.1:8010`

* **Health**
  `GET /health` → `{ "ok": true }`

* **Ingest** (upload PDFs)
  `POST /claims/{claim_id}/ingest` (multipart form; field name **files**; can send multiple)
  → `{ "claim_id": "...", "saved": [...], "input_dir": "samples/input_docs/<claim_id>" }`

* **Adjudicate** (run the whole pipeline)
  `POST /claims/{claim_id}/adjudicate?workers=6&build_index=true`
  → paths to artifacts + final confidence.

* **Report (Markdown)**
  `GET /claims/{claim_id}/report.md` → `text/markdown` (ready to render).

* **Search**
  `GET /claims/{claim_id}/search?q=keyword&k=10`

---

## Flask demo UI (this repo’s `server.py`)

### What it does

* Serves a small static site (`static/index.html`, `static/app.js`, `static/processing.gif`).
* On form submit, **proxies** your file to the FastAPI backend:

  1. `POST /claims/{claim_id}/ingest`
  2. `POST /claims/{claim_id}/adjudicate?workers=6&build_index=true`
  3. `GET  /claims/{claim_id}/report.md`
* Converts returned Markdown → HTML using **python-markdown** and returns that HTML to the browser.

### Configuration

* `MEDLEGAL_API_BASE` (env): where your FastAPI is listening.
  Defaults to `http://127.0.0.1:8010`.

### Run it

```bash
# ensure FastAPI is already running
python server.py
# → Flask dev server on http://127.0.0.1:5000
```

Open `http://127.0.0.1:5000`, choose a PDF, optionally type a Claim ID, then **Upload & Generate Report**.
The overlay shows while the pipeline runs; then the rendered report appears.

### Code pointers

* **`server.py`**

  * `/` → serves `static/index.html`
  * `/upload` → accepts `pdf` and optional `claim_id`, calls FastAPI, returns HTML (converted from Markdown):

    * uses `requests` with explicit timeouts (ingest: 60s, adjudicate: 600s, report: 60s)
    * catches upstream errors and returns JSON error messages

* **`static/index.html`**

  * Minimal form + styling; containers for overlay and final report.

* **`static/app.js`**

  * Handles form submit, shows “Processing…” overlay, posts to `/upload`, injects returned HTML into the page, and scrolls to it.

> If you ever move FastAPI to another host/port, set `MEDLEGAL_API_BASE` before launching Flask:
>
> ```bash
> set MEDLEGAL_API_BASE=http://127.0.0.1:9000   # Windows (cmd)
> # or
> export MEDLEGAL_API_BASE=http://127.0.0.1:9000 # macOS/Linux
> python server.py
> ```

### Requirements for the Flask UI

Make sure these are in `requirements.txt` (or pip-install them):

```
Flask
requests
markdown
```

(Your backend already needs `fastapi`, `uvicorn`, `google-generativeai`, `python-dotenv`, etc.)

---

## Artifacts per claim (where things land)

```
samples/
├── input_docs/<claim_id>/              # uploaded PDFs
└── processed/<claim_id>/
    ├── 01_pages/                       # single-page PDFs
    ├── 03_classified_pages/<Category>/ # copies, sorted by classifier
    ├── 04_docai_json/                  # raw DocAI JSON (ocr/classified fallback)
    ├── 07_text/
    │   ├── ALL.txt
    │   ├── manifest.json
    │   ├── citations.json
    │   └── chunks.jsonl                # after index build
    ├── 08_reports/
    │   ├── case.json
    │   ├── severity.json
    │   ├── severity_raw.txt
    │   ├── scoring.json
    │   └── <claim_id>_report.md
    └── index/
        └── index.db                    # SQLite FTS
```

---

## Reliability notes (things that match your current code)

* **Severity sometimes “defaults to 1”?**
  That means the model response wasn’t fully parseable, so the code bounded defaults.

  * Check `08_reports/severity_raw.txt` to see partial content.
  * If truncation is frequent for your documents, reduce `max_output_tokens` and/or batch size in `llm/severity.py`. The code already sanitizes and salvages JSON, but lowering batch size helps.

* **Windows Unicode errors**
  Writers use UTF-8 via `utils/io.py`. Avoid `Path.write_text()` without `encoding="utf-8"`.

* **SQLite “unable to open database file”**
  Ensure `samples/processed/<claim>/index` exists and is writable (the code creates dirs proactively).

* **UNIQUE constraint on `chunks.chunk_id`**
  Delete `samples/processed/<claim>/index/index.db` and rebuild; our indexer now normalizes chunk IDs to avoid collisions across reruns, but if you replaced code mid-run, clearing the DB is the safest reset.

* **Classifier looks “slow”**
  The classifier runs per page with `max_workers` from the API querystring. Increase it cautiously; the bottleneck is DocAI QPS and your network.

---

## Production tips (optional)

* Run both servers behind a reverse proxy (nginx/Caddy), terminate TLS there.
* Turn off `--reload` in production.
* Add auth to `/adjudicate` if you expose it outside localhost.
* Consider writing the final report as **PDF** too (e.g., use `weasyprint` or an HTML→PDF renderer) if you plan to email/share.

---

## FAQ

**Can I feed the LLM more structure?**
Yes—`collect_text.py` is deliberately “max coverage.” If you want stronger structure, you can augment with layout/tables later and append the raw text beneath so the LLM never loses signal.

**Can the front-end show intermediate artifacts?**
Add Flask routes that proxy FastAPI’s `/search` and render search hits; or expose direct download routes to `case.json`, `severity.json`, `scoring.json`.

**Do I need the “sifter” LLM stage?**
No; current design passes the full dossier to the case builder (with citations) and keeps severity isolated to avoid leakage of numeric scores.


