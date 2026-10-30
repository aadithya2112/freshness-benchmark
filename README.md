# Freshness Benchmark

An open benchmark of **client-observed insert, replacement, and deletion visibility** in vector databases during concurrent queries. Protocol 2 compares Qdrant, Weaviate, and pgvector with real retrieval datasets, version-aware probes, independent readers, quality checks, and downloadable evidence.

The reference experiment has four workloads (SciFact at 4k documents; Natural Questions at 10k and 100k, with steady and burst arrivals), five randomized trials per engine/workload, and 30 seconds of measured traffic per trial. It measures one machine and one declared configuration per engine. It is not a universal database ranking or a measurement of internal indexing time.

- [Live benchmark website](https://freshness-benchmark.vercel.app)
- [Final reference results and figures](results/mixed-v2/REPORT.md) — 60 trials, 19,350 confirmed mutations, and 18,000 background queries; all validity gates passed
- [Versioned release and exact data downloads](https://github.com/aadithya2112/freshness-benchmark/releases/tag/v0.5.0)
- [Protocol and interpretation](methodology.md)
- [Reproduce, verify, and extend](docs/publication-v2.md)
- [Machine-readable protocol](benchmarks/protocol-v2.json)
- [Website source](web/) — interactive comparisons, validity gates, trial inspection, and evidence downloads
- [Historical insert-only pilot](results/insert-v1/REPORT.md) — kept separate from protocol 2

## Run

Python 3.12, `uv`, and Docker are the reference environment. The Astro website build also needs Node 24+ and `npm ci --prefix web`. The core package supports Python 3.10+. Model weights and dataset archives are downloaded during preparation; no paid API is required. The full experiment rebuilds 60 collections, including 30 at 100k scale.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[publication]'
docker compose -p freshness-v2 -f docker-compose.v2.yml up -d
.venv/bin/python scripts/prepare_v2_data.py scifact --device cpu
.venv/bin/python scripts/prepare_v2_data.py nq --device cpu
.venv/bin/python -m unittest discover -s tests

# Functional smoke run; not a publication result.
.venv/bin/python scripts/run_streaming.py \
  --out artifacts/smoke-v2 --scenarios scifact-small --trials 1 --duration 1

# Complete reference protocol.
.venv/bin/python scripts/run_streaming.py \
  --out artifacts/my-v2 --trials 5 --duration 30
.venv/bin/python scripts/verify_v2.py artifacts/my-v2 --check-data
npm ci --prefix web
.venv/bin/python scripts/build_website.py artifacts/my-v2
python3 -m http.server 4173 --directory website/dist
```

Open `http://localhost:4173`. Downloadable evidence is generated from the experiment; charts contain no hand-entered results. The exact measured cache is identified by hashes. Regenerating vectors on another device can change floating-point values; report the new cache hash.

## What makes a comparison valid?

Readers start before write acknowledgement and independently inspect direct-ID state and unfiltered vector search. Updates require version 1, and deletions require absence on both channels. Each channel must produce three correct responses spanning 50ms. Separate background queries measure ANN recall against exhaustive cosine search and nDCG against relevance judgments.

All events stay in reliability denominators. A group qualifies only if every planned trial completes and passes arrival, probe-dispatch, query-dispatch, recall, precondition, capacity, cohort, and index-use checks. Failed cells remain inspectable. Latency percentiles describe successful events, and trial-level uncertainty is reported separately.

The workload includes observer traffic. Results include client, transport, and database costs. Static corpora with simulated mutations, 30-second trials, local Docker resource sharing, filtered quality queries, and five-trial uncertainty are explicit limits. See [methodology](methodology.md) before interpreting small differences.

## Contribute and cite

Submit complete experiments using [the contribution protocol](CONTRIBUTING.md). Cite the software/protocol version and exact result artifact using [CITATION.cff](CITATION.cff). Code is MIT; datasets retain their own attribution and licenses. The [legacy CLI](docs/legacy-cli.md) remains available for development and earlier experiments.
