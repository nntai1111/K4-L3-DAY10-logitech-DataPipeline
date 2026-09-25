# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules (from the user — always follow)

- **Always reply in Vietnamese.**
- **Ask before modifying code.** Describe the intended change and wait for approval before editing any file.
- **Never commit or push.** Leave `git commit` and `git push` to the user; at most, suggest a commit message.

## What this repo is

A team lab starter (VinUni AI20K, Day 10) for building a RAG data pipeline over Crossref paper metadata with data observability. It covers ingestion, cleaning, a Great Expectations 1.x quality gate plus a freshness SLA, a MiniLM + ChromaDB index, and evaluation. It then injects 6 kinds of data corruption, measures the metric drop, repairs from raw, and compares baseline, corrupted and repaired runs.

All former `TODO(student)` stubs are implemented: `ingestion/{crossref,cleaning,corruption}.py`, `evaluation/testset.py`, `observability/{quality,reporting}.py` and `pipelines/{phase1,corruption_flow,common}.py`. Don't change public function signatures, because other modules and the checkpoint smoke commands call them. The team is 3 people, and each member's commits on `main` are graded, so the user decides who commits what.

The docs (`README.md`, `docs/*.md`, `report/*.md`) and the stub docstrings are written in Vietnamese. `docs/Guide.md` is the step-by-step spec. `docs/CHECKPOINTS.md` defines the pass signal for each checkpoint (CP0–CP6).

## Setup & commands

`src/` is a setuptools `package-dir`, so the packages are imported top-level as `core`, `ingestion`, `retrieval`, `evaluation`, `observability` and `pipelines`, never as `src.core`. You must do an editable install, or both the scripts and the imports fail with `ModuleNotFoundError: No module named 'core'`.

```bash
uv sync                          # or: python -m venv .venv && .venv\Scripts\Activate.ps1 && python -m pip install -e .
cp .env.example .env             # set LLM_PROVIDER / LLM_MODEL / key; LLM_PROVIDER=mock needs no key
python script/run_phase1.py            # CP3: baseline end-to-end
python script/run_corruption_flow.py   # CP4–CP5: corrupt -> evaluate -> repair -> compare
```

Python must be 3.11–3.13; the code uses `datetime.UTC`. There is no lint config.

Tests live in `tests/` (pytest; the `dev` extra adds `pytest-cov`: `uv sync --extra dev` or `pip install -e ".[dev]"`). They run offline with `LLM_PROVIDER=mock` inside a temporary project copy of `data/raw/`, so they never touch real artifacts or spend LLM quota. The embedding model must already be in the Hugging Face cache, or be downloadable.

```bash
python script/run_tests.py                        # whole suite + coverage report, fails under 80%
python -m pytest tests/test_quality.py -q         # one file
python -m pytest tests/test_quality.py -k freshness   # one test by name
```

Per-stage smoke checks are the "single test" equivalents. Each prints a pass signal (full list in `docs/CHECKPOINTS.md`):

```bash
python -c "from core.config import load_settings; from ingestion.crossref import fetch_source_records; s=load_settings(); print(len(fetch_source_records(s)))"   # expect 24
python -c "from datetime import datetime, timezone; from core.config import load_settings; from ingestion.crossref import load_raw_records; from ingestion.cleaning import build_clean_dataframe; s=load_settings(); print(len(build_clean_dataframe(load_raw_records(s.paths.raw_records_json), datetime.now(timezone.utc))))"   # expect 24
python -c "from core.config import load_settings; from observability.quality import run_data_quality_checks; import pandas as pd; s=load_settings(); print(run_data_quality_checks(pd.read_json(s.paths.clean_json), s, 'test')['success'])"   # expect True
python -c "from core.config import load_settings; from evaluation.testset import build_test_set; import pandas as pd; s=load_settings(); print(len(build_test_set(pd.read_json(s.paths.clean_json), s.paths.eval_testset)))"   # expect 10
```

Environment flags read in code:
- `REFRESH_SOURCE=1`: fetch from the live API instead of the snapshot.
- `REFRESH_TEST_SET=1`: regenerate `test_set.json`.
- `RUN_RAGAS=1`: run the slow Ragas pass. It is skipped by default.
- `SKIP_AGENT_DEMO=1`: skip the tool-calling agent demo in phase 1 (saves LLM calls).
- `CROSSREF_MAILTO`: optional contact email for the Crossref polite pool in live mode.
- `LLM_PROVIDER`: one of `gemini`, `openai`, `anthropic`, `openrouter`, `ollama`, `custom`, `mock`.

The Gemini free tier is tiny (`gemini-2.5-flash`: 20 requests per day per model). Each phase-1 run spends about 6 calls on the agent demo. The judge only calls the LLM for answers that are not verbatim matches, which is about 5 per corruption run.

`load_settings()` loads the **parent directory's** `.env` first and the repo's `.env` second, and neither overrides values already set. A `.env` in the parent directory therefore wins.

## Architecture

**Pipeline stages:**

raw ingestion → clean → quality gate + freshness → embed/index → evaluate → corrupt → re-evaluate → repair from raw → 3-state report.

- **`core/config.py` is the single source of truth.** `load_settings()` returns a frozen `Settings` with a `Paths` dataclass that holds every artifact path: raw, clean, corrupted and repaired CSV/JSON, embedding manifests, quality reports, metrics, answers and reports. It also holds the fixed constants: `max_results=24`, `top_k=4`, `freshness_threshold_days=180`, the embedding model, and the three collection names. Always go through `settings.paths.*`. Hardcoded absolute paths cost points under the rubric.
- **Raw lineage and offline mode.** `data/raw/crossref_response.json` is the raw API payload, shaped as `message.items[]`. In it, `abstract` contains `<jats:p>` tags, `published.date-parts` holds the date, and authors are `{given, family}` objects. `data/raw/crossref_records.json` is the parsed `PaperRecord` list. Both are committed snapshots of 24 papers. Ingestion must fall back to the snapshot when the network fails or the API returns 429/503. **Repair must rebuild from the raw records rather than patch the corrupted frame**, so that repair is idempotent.
- **The cleaned DataFrame is the cross-module contract.** `LocalEmbeddingIndex._build_documents` (`retrieval/index.py`) reads `paper_id`, `title`, `text_for_embedding`, `published`, `authors_joined`, `categories_joined`, `summary`, `abs_url` and `pdf_url`. These become ChromaDB metadata, so they must be plain str/int/float values; for example, `published` must be a string, not a Timestamp. Quality and freshness checks also need `age_days` and `summary`. `text_for_embedding` has 5 lines: `Title:`, `Authors:`, `Published:`, `Categories:` and `Summary:`.
- **Three isolated Chroma collections share one persist dir, `data/chroma/`.** `LocalEmbeddingIndex.build(df, settings, embeddings_output_path)` picks `papers-baseline`, `papers-corrupted` or `papers-repaired` according to **which embeddings manifest path you pass**: `paths.embeddings_json`, `corrupted_embeddings_json` or `repaired_embeddings_json`. It deletes and recreates that collection, so rebuilds are idempotent. It then writes a JSON manifest, which `LocalEmbeddingIndex.load()` reads back.
- **QA is extractive, not LLM-generated.** `retrieval/qa.answer_question` does an exact lookup when the question contains a **single-quoted title**, runs semantic search, and then picks the answer field by phrasing:
  - "who authored" or "list the authors" → `authors_joined`
  - "when was", "publication date" or "published on" → `published`
  - "what categories" → `categories_joined`
  - anything else → the first sentence of `summary`

  So `evaluation/testset.py` must word its questions to match these patterns and put titles in single quotes. `ground_truth` values must match those metadata fields, or Token F1 collapses. Each test item has `id`, `question_type` (`summary`, `authors`, `date` or `categories`), `question`, `ground_truth` and `ground_truth_doc_ids`. There are 10 items.
- **Evaluation** is in `evaluation/metrics.evaluate_pipeline`. It computes `retrieval_hit_rate` (any retrieved `paper_id` is in `ground_truth_doc_ids`), `mean_token_f1`, and LLM-judge `judge_accuracy` / `mean_judge_score`. Baseline, corrupted and repaired runs must all use the same `test_set.json`; `load_or_build_test_set` keeps it fixed.
  - Each answer records a `judge_source`:
    - `exact_match`: a verbatim match, scored 5 with no LLM call.
    - `cache`: a verdict reused from `data/results/judge_cache.json`, keyed by provider, model and prompt.
    - `llm`: a fresh LLM verdict.
    - `fallback`: the Token F1 heuristic, used when the LLM fails.
  - A daily-quota error (`RESOURCE_EXHAUSTED`) stops LLM judging for the rest of the run.
- **Gate before index.** `phase1` runs the GX gate before indexing and exits without indexing when it fails. `corruption_flow` deliberately indexes the corrupted data to measure the silent failure. When the gate fails, it auto-repairs from `data/raw/crossref_records.json` and proves idempotency with `dataset_fingerprint` (two repair runs plus the baseline). It writes `data/results/repair_log.json`.
- **GX suite (`observability/quality.py`).** The 4 required expectation types plus extended checks. Each corruption has a dedicated detector:
  - title length ≥ 8 for truncation
  - a noise regex for injected garbage
  - DOI and ISO-date regexes
  - schema columns
  - `source_papers_present`, which reconciles against the raw snapshot to catch dropped records
  - the freshness SLA, which catches stale dates
- **Corruption is seeded** (`SEED = 42`), so reruns give the same corrupted dataset. Scenarios 2–5 hit disjoint rows.
- **`retrieval/agent.py`** is a separate LangChain `create_agent` tool-calling agent with two tools, `semantic_search_papers` and `lookup_paper`. It is meant for demos; the metrics come from `qa.py`. `retrieval/llm.build_llm` is the multi-provider router.

## Hard requirements (graded)

- **Use Great Expectations 1.x syntax only:** `gx.get_context(mode="ephemeral")`, then `context.data_sources.add_pandas(...)`, `.add_dataframe_asset(...)`, `.add_batch_definition_whole_dataframe(...)` and `.get_batch(batch_parameters={"dataframe": df})`. Never use the legacy `context.sources.pandas_default`.
  - Required expectations: `ExpectTableRowCountToBeBetween` (5–5000), `ExpectColumnValuesToNotBeNull` (`paper_id`, `title`, `text_for_embedding`), `ExpectColumnValuesToBeUnique` (`paper_id`) and `ExpectColumnValueLengthsToBeBetween` (`summary` ≥ 30).
  - `run_data_quality_checks` must return a dict with a `"success"` key.
- **Freshness:** a row is stale when `age_days > 180`. Set `is_fresh = False` when more than 25% of rows are stale.
- **The 6 corruptions:**
  - drop the latest 20% of records
  - blank summaries
  - inject noise into summaries
  - truncate titles to under 8 characters
  - shift published dates back 365 days
  - duplicate rows

  After corrupting, rebuild `text_for_embedding` and log every corruption to `paths.corruption_log`.
- **Metrics and reports must come from real runs** of the two scripts. Never hand-edit numbers in `data/results/*.json` or `data/reports/*.md`; the rules treat that as academic misconduct. Never commit `.env`.
