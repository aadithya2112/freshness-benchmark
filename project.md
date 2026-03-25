# Project Summary

This project benchmarks vector-search freshness: the time between document submission and the first successful retrieval for that document.

Primary metric:

`Freshness Latency = T(searchable) - T(submitted)`

The benchmark also records:

- embedding latency
- backend write acknowledgement latency
- search visibility latency after write acknowledgement

## Current Scope

- Python CLI with:
  - `run` for a single benchmark
  - `compare` for a backend/rate/mode matrix
  - `report` for HTML generation from run artifacts
- Backend adapters:
  - Qdrant
  - Weaviate
  - pgvector
- Embedding modes:
  - `precomputed` for apples-to-apples backend comparisons
  - `live` for end-to-end ingest freshness
- Synthetic workload profiles with deterministic retrieval anchors
- HTML reports for both single runs and comparison matrices

## Intended Use

- Compare vector stores fairly with fixed vectors
- Measure real ingest freshness with live embeddings
- Produce reproducible artifacts that other developers can rerun locally
