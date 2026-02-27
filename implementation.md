# Implementation Details

## 1) Architecture Overview

The project is a Python CLI benchmark with two flows:

- `run`: executes ingestion -> embedding -> indexing -> retrieval checks and writes artifacts.
- `report`: reads artifacts and generates a single-page HTML visualization.

Core design goals:

- Keep the MVP simple and deterministic.
- Capture exact lifecycle timestamps per document.
- Produce artifacts that are easy to inspect and demo.

## 2) Runtime Pipeline (`run`)

The benchmark runs in a single process at a configured steady rate (`--rate` docs/sec).

Per document:

1. Generate synthetic text with a unique anchor phrase and deterministic `doc_id`.
2. Record `t_ingested` right before sending work into the embedding/index path.
3. Call embedding API (OpenRouter OpenAI-compatible endpoint) and record `t_embedding_done`.
4. Upsert vector + payload into Qdrant and record `t_index_update_done`.
5. Poll vector search until top-K contains the same `doc_id`; record `t_first_search_success`.
6. Compute:
   - `embedding_ms = t_embedding_done - t_ingested`
   - `index_ack_ms = t_index_update_done - t_embedding_done`
   - `freshness_ms = t_first_search_success - t_ingested`

If top-K match does not happen within `--max-wait-s`, the document is marked `timeout`.
If any API step fails, the document is marked `error`.

## 3) Module Responsibilities

- `src/freshness_benchmark/cli.py`
  - Entry point and command routing (`run`, `report`).
- `src/freshness_benchmark/config.py`
  - CLI argument definitions and runtime config construction.
- `src/freshness_benchmark/models.py`
  - Data models: `BenchmarkConfig`, `DocLifecycle`, `RunSummary`.
  - Timestamp and duration helpers.
- `src/freshness_benchmark/embeddings.py`
  - Embedding client wrapper over `/embeddings` HTTP call.
  - Provider-to-env-key resolution (`OPENROUTER_API_KEY` / `OPENAI_API_KEY`).
- `src/freshness_benchmark/qdrant_backend.py`
  - Qdrant collection creation, upsert, and search.
  - Success rule helper (`match_doc_in_hits`) and idempotent collection handling.
- `src/freshness_benchmark/runner.py`
  - Main orchestration loop, pacing, timestamp capture, timeout/error handling.
- `src/freshness_benchmark/reporting.py`
  - Percentiles/stat aggregation, artifact writes, and console summary.
- `src/freshness_benchmark/visualize.py`
  - Reads `summary.json` + `metrics.csv` and renders `report.html` (KPI cards + charts).

## 4) Data and Output Contracts

Each run writes to `artifacts/<run_id>/`:

- `trace.jsonl`
  - One JSON object per document with raw timestamps, status, and derived metrics.
- `metrics.csv`
  - Tabular per-document view, useful for spreadsheets and ad-hoc analysis.
- `summary.json`
  - Aggregates: totals, success rate, and p50/p95/p99 stats for key metrics.
- `report.html` (when `report` command is run)
  - One-page visual report for demo use.

Important statuses:

- `success`: document became searchable in top-K.
- `timeout`: search visibility not reached before timeout.
- `error`: API/runtime failure prevented completion.

## 5) Visualization Flow (`report`)

`report` does not rerun benchmarking. It reads existing artifacts:

- Finds run directory (`--run-dir` or latest in `--artifacts-dir`).
- Parses `summary.json` and `metrics.csv`.
- Builds:
  - Headline KPI cards (success + freshness percentiles).
  - Freshness histogram.
  - Freshness CDF.
  - Stage breakdown bars (embedding, index ack, inferred search visibility gap).
- Writes `report.html` in run dir (or `--out-file`).

## 6) Error Handling and Practical Behavior

- Missing required API key fails early with a clear error.
- Qdrant collection creation is idempotent across reruns (existing collection conflict is ignored).
- Search endpoint compatibility includes query/search fallback behavior.
- Runner continues document-by-document; one doc failure does not abort the entire run.

## 7) Test Coverage

Tests are in `tests/`:

- Metric computation and percentile logic.
- Success rule correctness for top-K matching.
- Timeout behavior.
- Qdrant collection idempotency behavior.
- Visualization utility behavior (histogram/CDF/latest-run/report generation).

This is MVP-grade coverage focused on correctness of benchmark semantics and repeatability of outputs.

## 8) Current MVP Boundaries

- Single-process benchmark loop (not distributed load generation).
- Synthetic corpus, not production content.
- Single vector backend path (Qdrant) and provider-focused setup.
- External embedding latency depends on network/provider conditions.
