# Freshness Benchmark — insert visibility protocol v1

## Claim and scope

Measure the elapsed time between submitting an insert to the client pipeline and receiving the first successful top-k self-vector search response. A match requires the expected document ID. This is an **observation upper bound on retrievability**, including client scheduling, write acknowledgement, transport, search queueing and query time. It is not the exact instant an index changes.

The initial publication track is local, single-node insertion into a populated index. It uses real documentation and cached semantic vectors. It supports comparisons of these particular configurations and resource budgets. It does not establish semantic relevance, update/delete freshness, durability equivalence, distributed consistency, production-scale performance or a universal backend ranking.

## Timing and observation

All elapsed metrics use `time.monotonic()`. UTC timestamps support audit and correlation only. The admission schedule is open loop: a configured fixed interval independent of prior completion. Scheduling lateness is recorded separately. Latency begins at actual submission; use the scheduling diagnostic to detect an overloaded load generator.

- `freshness_ms`: submission → first successful search response received.
- `embedding_ms`: submission → vector available, including embedding worker queue.
- `write_ack_ms`: vector available → acknowledgement, including write worker queue.
- `visibility_ms`: acknowledgement → successful response, including probe queue and query time.

These stages are client-observed durations, not server profiling measurements. Cached vectors are generated, loaded, and validated before the measured phase. Per-document cache lookups remain in the timed pipeline.

The visibility scheduler dispatches one request per document at a time. A document waiting for its next poll does not reserve a search worker. Poll interval is a minimum gap after an unsuccessful response, not an assertion of constant temporal resolution. Each probe records request start, response end and match outcome relative to submission. A first successful response bounds visibility from above. Negative ANN results can be ranking misses, so they do not prove absence or justify a tighter lower bound than zero.

The deadline is measured from submission, including all queues. Responses received after the deadline remain timeouts even if they contain a match. Requests already in flight may finish after the deadline; HTTP transport timeouts are 20 seconds. An embedding/write error is an error, distinct from a visibility timeout. All submitted records remain in traces and reliability denominators.

Latency quantiles are conditional on successful observations. Read them with success rate and fractions of **all** submissions observed within 10/50/100/1000ms. Failures cannot improve these fractions. Completion rate counts successes per measurement wall time; arrival rate uses `(N-1)/(last submission - first admission origin)` and is zero for a one-document run.

## Data

The real corpus is derived from the official Python 3.13.0 release archive:
https://www.python.org/ftp/python/3.13.0/Python-3.13.0.tgz

Retain `PYTHON-LICENSE.txt` generated alongside the data. Python documentation is covered by PSF License Version 2; see https://docs.python.org/3.13/license.html. The transformation selects `Doc/library`, `Doc/tutorial`, and `Doc/howto` RST files, in sorted path order, splits on whitespace into nonoverlapping 100-word chunks, discards chunks below 40 words and exact text duplicates, then shuffles using seed 20261028. This produces 9,383 records. RST directives and code examples remain part of the workload. The generated manifest and committed lock pin source and corpus SHA-256 values.

Embeddings use `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions, normalized, CPU inference, 256-token truncation. Model card and Apache-2.0 license: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2. The cache includes per-document text hashes; mismatches, missing vectors, wrong dimensions, zero and nonfinite vectors fail validation. Floating-point regeneration can differ across platforms; the recorded cache hash identifies exact inputs for a comparison.

No retrieval anchors are injected in the publication track. The older `precomputed` mode without `--embedding-cache` generates hash-based synthetic vectors; it is a control and smoke workload. The bundled 120-record docs pack is templated synthetic content, not a real-world corpus.

## Execution and backend settings

Publication defaults: five independent trials, two rates (50 and 200 documents/s), three backends, 2,000 preloads and 1,000 measured inserts per cell. All trials use the same disjoint preload and measured subsets. Repetitions measure execution variance on a fixed sample, not uncertainty over all possible datasets.

The 30 cells are shuffled with seed 20261028. Each cell creates a fresh collection/table, preventing earlier trial data from entering retrieval. Preloads finish before measurement. A deterministic evenly spaced sample of up to 32 preloaded records must be searchable before admission begins. This is a readiness check, not proof that every background index task has completed. There is no measured-data warmup: initial connection and cache effects belong to the insertion workload. Creation/setup is outside timing for cached vectors.

Collection-wide search includes preload documents. Legacy run-filtered searches remain available for small smoke tests and must not be presented as whole-corpus comparisons. Collection-wide runs require dedicated collections; the publication runner creates them automatically.

All three containers receive 2 CPU and 2 GiB memory limits; the client runs on the host. Other containers remain idle while a cell runs. Docker Desktop and host activity can influence results. These are controlled local resource limits, not dedicated physical-machine isolation.

Compose images are pinned by digest to the actually tested versions. These intentionally represent a reproducible version snapshot, not claims about the newest releases. Backend defaults are retained and effective settings recorded. Qdrant writes use `wait=true`; Weaviate uses synchronous individual object POSTs; PostgreSQL uses autocommit INSERTs and an HNSW cosine index with separate connections per worker. Acknowledgements have different backend semantics; no equal-durability claim is made. Index creation failures fail the run. PostgreSQL's planner and Qdrant's thresholds may choose exact scanning for this small corpus; inspect the recorded settings. This track compares searchable service behavior, not guaranteed ANN execution plans or equal recall operating points.

## Statistics and validity gates

Report the median of independent trial p50/p95 values. The 95% interval for the median trial p95 uses 10,000 percentile bootstrap resamples of trial p95s, seed 20261028. Five repetitions give limited uncertainty resolution; do not infer statistical significance from these intervals. P99 may appear in individual summaries but is not a headline at this sample size. Pooled CDFs are descriptive; they retain all submissions in the denominator.

Before interpreting a cell as a backend comparison:

1. All five planned trials must be present, each with the requested record count.
2. Each trial's p95 admission scheduling delay must be no greater than one requested interarrival interval.
3. Each trial's p95 first-probe queue must be ≤10ms, matching the configured polling gap.
4. Inspect success, errors, timeouts, raw probes and actual arrival rates alongside latency.

Failed gates are displayed and retained, not silently excluded. These gates detect important client effects; passing them does not eliminate polling uncertainty, relevance differences or host noise.

## Reproducibility and submission policy

Follow `docs/publication.md`. Preserve experiment order, data/cache hashes, dependencies, Docker image IDs/settings, source snapshot, raw lifecycle traces, per-run summaries and aggregate checksums. Publish exact versions and parameters with results. Never compare legacy synthetic-pack numbers directly against this protocol.

Community submissions must provide the same evidence, disclose every tuning change and resource difference, and keep raw failures. Label externally supplied results as unverified until independently reproduced. New adapters must implement the backend contract, preserve collection-wide retrieval and acknowledgement semantics, and pass correctness plus real-data smoke checks. A new dataset or incompatible measurement change requires a new protocol/result series.
