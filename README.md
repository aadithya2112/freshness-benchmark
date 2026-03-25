# Freshness Benchmark V2

Benchmark how long it takes for a document to become searchable after submission.

Primary metric:

`freshness_ms = t_searchable - t_submitted`

Stage metrics:

- `embedding_ms = t_embedding_done - t_submitted`
- `write_ack_ms = t_write_acked - t_embedding_done`
- `visibility_ms = t_searchable - t_write_acked`

The benchmark supports:

- Backends: `qdrant`, `weaviate`, `pgvector`
- Embedding modes:
  - `precomputed` for backend-only fairness
  - `live` for real end-to-end ingest latency
- Workload profiles:
  - `synthetic-small`
  - `synthetic-medium`
  - `synthetic-large`
  - `dataset`
- Benchmark-pack presets:
  - `baseline_docs_precomputed`
  - `baseline_synthetic_precomputed`
  - `embedding_reality_check`

## Requirements

- Python 3.10+
- Docker
- `OPENROUTER_API_KEY` or `OPENAI_API_KEY` only when using `--embedding-mode live`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Start Local Backends

```bash
docker compose up -d
```

Services:

- Qdrant: `http://localhost:6333`
- Weaviate: `http://localhost:8080`
- pgvector/Postgres: `postgresql://postgres:postgres@localhost:5432/freshness`

## Run A Single Benchmark

Backend-only fairness run:

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli run \
  --backend qdrant \
  --embedding-mode precomputed \
  --docs 200 \
  --rate 5 \
  --workload synthetic-medium
```

Live end-to-end run:

```bash
export OPENROUTER_API_KEY=your_key_here
PYTHONPATH=src python3 -m freshness_benchmark.cli run \
  --backend weaviate \
  --embedding-mode live \
  --embedding-model text-embedding-3-small \
  --provider openrouter \
  --docs 100 \
  --rate 3
```

Useful flags:

```text
--backend qdrant|weaviate|pgvector
--embedding-mode live|precomputed
--embedding-concurrency 4
--write-concurrency 4
--search-concurrency 8
--workload synthetic-small|synthetic-medium|synthetic-large|dataset
--dataset-path ./corpus.jsonl
--dataset-format jsonl|text-dir
--text-field body
--id-field slug
--top-k 10
--poll-interval-ms 250
--max-wait-s 120
```

Real-data local corpus run:

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli run \
  --backend qdrant \
  --embedding-mode precomputed \
  --workload dataset \
  --dataset-path tests/fixtures/sample.jsonl \
  --dataset-format jsonl \
  --text-field body \
  --id-field slug \
  --docs 3 \
  --rate 2
```

## Run A Comparison Matrix

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli compare \
  --backends qdrant weaviate pgvector \
  --rates 2 5 10 \
  --embedding-modes precomputed \
  --docs 200 \
  --workload synthetic-medium
```

Add `live` to `--embedding-modes` when you want end-to-end comparisons and have API credentials configured.

## Run The Publishable Benchmark Pack

Canonical command:

```bash
scripts/run_benchmark_pack.sh --pack-id baseline-pack
```

This runs the two pinned precomputed presets and writes:

- `benchmark_pack.json`
- `benchmark_pack.csv`
- `benchmark_pack.html`

Add the live realism-check preset when credentials are configured:

```bash
export OPENROUTER_API_KEY=your_key_here
scripts/run_benchmark_pack.sh \
  --pack-id baseline-pack-live \
  --presets baseline_docs_precomputed baseline_synthetic_precomputed embedding_reality_check
```

The bundled docs-style corpus lives at `benchmarks/corpora/docs_pack.jsonl`.

Required local smoke gates before extending the benchmark further:

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli compare \
  --backends qdrant weaviate pgvector \
  --rates 2 \
  --embedding-modes precomputed \
  --docs 5 \
  --workload synthetic-small
```

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli compare \
  --backends qdrant weaviate pgvector \
  --rates 2 \
  --embedding-modes precomputed \
  --docs 3 \
  --workload dataset \
  --dataset-path tests/fixtures/sample.jsonl \
  --dataset-format jsonl \
  --text-field body \
  --id-field slug
```

## Outputs

Single run artifacts under `artifacts/<run-id>/`:

- `trace.jsonl`
- `metrics.csv`
- `summary.json`
- `report.html`

Comparison artifacts under `artifacts/<compare-id>/`:

- `comparison.json`
- `comparison.csv`
- `comparison.html`
- `runs/<run-id>/...` for each underlying run

Benchmark-pack artifacts under `artifacts/<pack-id>/`:

- `benchmark_pack.json`
- `benchmark_pack.csv`
- `benchmark_pack.html`
- `presets/<preset>/trial-<n>/comparison.{json,csv,html}`

## Report Generation

Regenerate the latest single-run HTML report:

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli report
```

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## Methodology

See `methodology.md` for the benchmark definition, fairness rationale, anchor-injection explanation, pinned presets, and validation gates.
