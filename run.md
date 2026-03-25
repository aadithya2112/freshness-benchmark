# Run Instructions

## 1) Setup

```bash
cd /Users/aadithya/Projects/freshness-benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 2) Start Local Backends

```bash
docker compose up -d
```

## 3) Run A Reproducible Backend Comparison

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli compare \
  --backends qdrant weaviate pgvector \
  --rates 2 5 10 \
  --embedding-modes precomputed \
  --docs 200 \
  --workload synthetic-medium
```

## 4) Run A Single End-To-End Live Benchmark

```bash
export OPENROUTER_API_KEY=your_key_here
PYTHONPATH=src python3 -m freshness_benchmark.cli run \
  --backend qdrant \
  --embedding-mode live \
  --embedding-model text-embedding-3-small \
  --docs 100 \
  --rate 3
```

## 5) Run A Real-Data Local Corpus Benchmark

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

## 6) Run The Required Smoke Gates

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

## 7) Run The Benchmark Pack

```bash
scripts/run_benchmark_pack.sh --pack-id baseline-pack
```

Optional live realism check:

```bash
export OPENROUTER_API_KEY=your_key_here
scripts/run_benchmark_pack.sh \
  --pack-id baseline-pack-live \
  --presets baseline_docs_precomputed baseline_synthetic_precomputed embedding_reality_check
```

## 8) Generate A Report For The Latest Single Run

```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli report
```

Outputs:

- Single run: `artifacts/<run-id>/trace.jsonl`, `metrics.csv`, `summary.json`, `report.html`
- Comparison: `artifacts/<compare-id>/comparison.json`, `comparison.csv`, `comparison.html`
- Benchmark pack: `artifacts/<pack-id>/benchmark_pack.json`, `benchmark_pack.csv`, `benchmark_pack.html`
