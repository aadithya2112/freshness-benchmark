> Historical development notes. For the current public comparison protocol, see [methodology.md](methodology.md) and [docs/publication.md](docs/publication.md).

# Implementation Details

## Architecture

The benchmark is a Python CLI with three workflows:

- `run`: execute one pipelined freshness benchmark
- `compare`: execute a matrix of runs across backends, rates, and embedding modes
- `report`: regenerate a single-run HTML report from artifacts

## Runtime Pipeline

Each document moves through independent stages:

1. Submission at a target ingest rate
2. Embedding generation or deterministic vector lookup
3. Backend upsert and write acknowledgement
4. Polling until the document is searchable

The runner is pipelined, not serial:

- later docs can be submitted while earlier docs are still embedding
- writes are bounded by `--write-concurrency`
- visibility polling is independent from embedding and write stages

Workload inputs now support:

- synthetic profiles
- local JSONL corpora
- local text/Markdown directory corpora

For dataset-backed runs, the benchmark injects a deterministic retrieval anchor into the benchmarked copy of each document while preserving the original source text separately in the trace metadata.

## Adapters And Sources

- Embedding source contract:
  - `get_vector(doc_id, text)`
  - `dimensions`
  - `metadata`
- Backend adapter contract:
  - `prepare_run(vector_size)`
  - `upsert(doc_id, vector, payload)`
  - `search(vector, limit)`
  - `reset_run_data()`
  - `backend_info()`
  - `close()`

Implemented backends:

- Qdrant via HTTP
- Weaviate via HTTP
- pgvector via `psycopg`

## Artifacts

Per run:

- `trace.jsonl`: raw per-document lifecycle records
- `metrics.csv`: tabular per-document metrics
- `summary.json`: run-level percentiles, rates, backend info, environment metadata
- `summary.json` also records dataset configuration when `--workload dataset`
- `report.html`: single-run HTML report

Per comparison:

- `comparison.json`: aggregated comparison rows
- `comparison.csv`: tabular comparison results
- `comparison.html`: comparison dashboard

## Metrics

- `embedding_ms`
- `write_ack_ms`
- `visibility_ms`
- `freshness_ms`

Percentiles are reported for p50, p95, and p99, plus min/max.

## Reproducibility Choices

- `precomputed` mode provides deterministic vectors for fair backend comparisons
- run metadata includes backend target details, host metadata, and Docker images when available
- workload profiles keep retrieval deterministic with unique anchors while varying text size
- local smoke gating is validated with one synthetic compare and one dataset-backed compare across `qdrant`, `weaviate`, and `pgvector`
