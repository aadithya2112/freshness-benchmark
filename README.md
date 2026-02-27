# Freshness Benchmark MVP

Quick benchmark for vector-search freshness:

`Freshness Latency = T(searchable) - T(ingested)`

Detailed implementation notes: see `implementation.md`.

It measures, per document:
- `t_ingested`
- `t_embedding_done`
- `t_index_update_done`
- `t_first_search_success`

## Requirements

- Python 3.10+
- Docker (for local Qdrant)
- `OPENROUTER_API_KEY` set in environment

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Start Qdrant

```bash
docker compose up -d
```

Qdrant will be available at `http://localhost:6333`.

## Run benchmark

```bash
export OPENROUTER_API_KEY=your_key_here
python -m freshness_benchmark.cli run --docs 200 --rate 5
```

## CLI options

```text
python -m freshness_benchmark.cli run \
  --docs 200 \
  --rate 5 \
  --collection freshness_benchmark \
  --qdrant-url http://localhost:6333 \
  --embedding-model text-embedding-3-small \
  --provider openrouter \
  --base-url https://openrouter.ai/api/v1 \
  --top-k 10 \
  --poll-interval-ms 250 \
  --max-wait-s 120 \
  --out-dir ./artifacts/<run-id>
```

`OPENROUTER_MODEL` can be set to override `--embedding-model`.

## Outputs

Each run writes to `artifacts/<run_id>/`:
- `trace.jsonl` (one lifecycle record per doc)
- `metrics.csv` (tabular lifecycle + latency)
- `summary.json` (aggregates + run config)

## Generate HTML report

Generate a one-page visualization report (KPI cards + histogram + CDF + stage breakdown):

```bash
PYTHONPATH=src python -m freshness_benchmark.cli report
```

By default this picks the latest run in `artifacts/` and writes:

`artifacts/<latest-run>/report.html`

Optional:

```bash
PYTHONPATH=src python -m freshness_benchmark.cli report \
  --run-dir artifacts/20260227T163212Z \
  --out-file artifacts/20260227T163212Z/report.html
```

## Run tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```
