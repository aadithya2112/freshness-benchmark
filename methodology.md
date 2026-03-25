# Methodology

## What Freshness Means

The benchmark measures how long it takes for a newly submitted document to become searchable through vector search.

Primary metric:

`freshness_ms = t_searchable - t_submitted`

Stage metrics:

- `embedding_ms = t_embedding_done - t_submitted`
- `write_ack_ms = t_write_acked - t_embedding_done`
- `visibility_ms = t_searchable - t_write_acked`

The primary metric is the headline number because it matches the user-facing question. The stage metrics exist to explain where time is being spent.

## Fairness Baseline

The benchmark pack uses `precomputed` mode as the fairness baseline.

Why:

- it removes embedding-provider latency and network variance from backend comparisons
- it isolates backend write and search-visibility behavior
- it makes repeated local trials easier to compare

The pack also defines one `live` preset as a realism check. That preset is narrower and smaller on purpose. It shows what embedding generation adds to the full path, but it is not the headline comparison.

## Why Dataset Runs Use Anchor Injection

Dataset-backed runs inject a deterministic retrieval anchor into the indexed copy of each document.

Why:

- the benchmark needs one backend-agnostic success rule
- raw semantic relevance would make the benchmark depend on ranking behavior rather than freshness
- the anchor lets the runner query by the document's own vector and confirm that the expected document appears in the top-k results

The original source text is still preserved separately in the trace so the benchmark remains auditable.

## Pinned Benchmark Pack

Bundled corpus:

- path: `benchmarks/corpora/docs_pack.jsonl`
- fields: `doc_id`, `title`, `section`, `url`, `body`
- size: 120 short docs-style records

Pinned presets:

- `baseline_docs_precomputed`
  - backends: `qdrant`, `weaviate`, `pgvector`
  - rates: `2`, `5`, `10` docs/s
  - workload: bundled docs corpus
  - mode: `precomputed`
  - docs per run: `60`
- `baseline_synthetic_precomputed`
  - backends: `qdrant`, `weaviate`, `pgvector`
  - rates: `2`, `5`, `10` docs/s
  - workload: `synthetic-medium`
  - mode: `precomputed`
  - docs per run: `60`
- `embedding_reality_check`
  - backend: `qdrant`
  - rate: `2` docs/s
  - workload: bundled docs corpus
  - mode: `live`
  - model: `text-embedding-3-small`
  - docs per run: `24`

Trial rule:

- every preset is intended to run for `3` trials
- the pack aggregates the median of:
  - p50 freshness
  - p95 freshness
  - success rate
  - achieved submission rate
  - achieved completion rate

## Reproducibility

Canonical command:

```bash
scripts/run_benchmark_pack.sh --pack-id baseline-pack
```

Optional live preset:

```bash
export OPENROUTER_API_KEY=your_key_here
scripts/run_benchmark_pack.sh \
  --pack-id baseline-pack-live \
  --presets baseline_docs_precomputed baseline_synthetic_precomputed embedding_reality_check
```

Artifacts:

- `benchmark_pack.json`
- `benchmark_pack.csv`
- `benchmark_pack.html`
- `presets/<preset>/trial-<n>/comparison.json`
- `presets/<preset>/trial-<n>/comparison.csv`
- `presets/<preset>/trial-<n>/comparison.html`

## Validation Gates

Smoke gates that should stay green:

- synthetic local compare across `qdrant`, `weaviate`, and `pgvector`
- dataset local compare across `qdrant`, `weaviate`, and `pgvector`

Benchmark-pack validation before presentation:

- all three backends succeed on the bundled docs corpus in `precomputed` mode at `2 docs/s`
- at least one higher-rate run (`5` or `10 docs/s`) completes per backend
- `benchmark_pack.html` is generated successfully
