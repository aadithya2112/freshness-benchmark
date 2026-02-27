# Run Instructions

## 1) Setup
```bash
cd /Users/aadithya/Projects/freshness-benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 2) Configure API key
```bash
echo "OPENROUTER_API_KEY=your_key_here" > .env
```

## 3) Start Qdrant
```bash
docker compose up -d
```

## 4) Run benchmark
```bash
set -a; source .env; set +a
PYTHONPATH=src python3 -m freshness_benchmark.cli run --docs 200 --rate 5
```

## 5) Generate HTML report
```bash
PYTHONPATH=src python3 -m freshness_benchmark.cli report
```

Outputs are written under `artifacts/<run_id>/`:
- `trace.jsonl`
- `metrics.csv`
- `summary.json`
- `report.html`
