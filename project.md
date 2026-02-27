# Project Summary

This project benchmarks vector-search freshness: how long it takes for an ingested document to become retrievable in search.

It records per-document timestamps for ingestion, embedding completion, index update completion, and first successful retrieval, then computes:

`Freshness Latency = T(searchable) - T(ingested)`

## Implementation (MVP)

- Python CLI with two commands:
  - `run`: executes the benchmark and writes artifacts.
  - `report`: builds a one-page HTML visualization from run artifacts.
- Synthetic documents are generated with unique anchors for deterministic retrieval checks.
- Embeddings are requested from OpenRouter (OpenAI-compatible `/embeddings` API).
- Vectors are upserted into local Qdrant, then polled until the doc appears in top-K search.
- Each run writes `trace.jsonl`, `metrics.csv`, `summary.json`, and `report.html` under `artifacts/<run_id>/`.

## Limitations

- MVP is single-backend (local Qdrant) and single-provider focused.
- Embedding latency includes external API/network variability.
- Uses synthetic documents (not production traffic/content).
- Single-process runner; not a high-concurrency load test.
