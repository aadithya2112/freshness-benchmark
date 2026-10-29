# Mixed-mutation visibility protocol 2

Protocol identifier: `mixed-mutations-v2`. Reference configuration: [protocol-v2.json](benchmarks/protocol-v2.json). Software release: 0.5.0.

## Research question and scope

How quickly does a submitted insert, replacement, or deletion become observable through a vector database's public APIs, while independent readers and writers operate concurrently, at a declared retrieval-quality level?

This is a single-node, client-observed comparison. It includes client scheduling, serialization, transport, server execution, and the observation procedure. It does not isolate index maintenance time, prove linearizability or durability, measure distributed replication, or establish a capacity limit. Static retrieval corpora supply real text and questions; mutations are simulated, not historical replays.

## Data and workload

The reference uses BEIR distributions of SciFact and Natural Questions. Select 100 test queries with seed 20261028, retain all judged relevant documents first, then sample remaining documents with a seeded reservoir. Cache all 5,183 SciFact documents and 124,000 NQ documents. The immutable quality cohort contains the first 4,000 SciFact documents or the first 10,000/100,000 NQ documents. All selected relevance judgments remain inside that cohort. Relevant-first sampling makes this a declared retrieval subset; its nDCG scores are not comparable to the full BEIR leaderboard.

Normalize 384-dimensional float32 vectors from `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Input is a title/text prefix of at most 200 whitespace words, followed by the model's 256-token truncation. Preparation and encoding occur outside the timed experiment. The reference cache was encoded with Apple MPS. CPU regeneration can differ numerically. Archives, transformations, licenses, vector caches, and source revisions are hashed in the manifests.

Each measured operation uses a disjoint document ID, exactly once. Inserts create a new document; updates replace content and vector under the same ID, changing version 0 to 1; deletions remove an existing version-0 document. Operations rotate insert/update/delete in equal proportions. Old update vectors are selected with cosine similarity at most 0.3 to the replacement vector. Every update must also be absent from the new-vector top-10 search before admission. Old update/delete targets must be retrievable before measurement. No target is silently dropped because a precondition fails.

All profiles use 10 mutation submissions and 10 independent background queries per second. The burst profile increases mutation arrivals to 40/s for the first second of every ten-second period. A 30-second steady trial offers 300 operations; a burst trial offers 390. Rate means mutations only: observation reads and quality queries add load. This distinction matters when interpreting throughput.

## Preparation and experimental unit

Each trial creates a new collection and preloads the immutable corpus plus initial mutable targets. It finishes index construction and checks cardinality/readiness. Qdrant requires at least 95% indexed vectors; its small remaining/unindexed segments can still use a scan. This is a configured HNSW database track, not a claim that every candidate is found exclusively through HNSW. PostgreSQL records an actual EXPLAIN plan with its HNSW index selected; sequential scan is disabled for this track. Weaviate records HNSW configuration with flat-search cutoff zero.

Every mutation precondition is verified before a two-second excluded query warmup. An idle query baseline then covers all 100 questions, taking ten seconds at the reference rate. The mixed measured phase admits work for 30 seconds, then drains outstanding requests. Timeouts are five seconds from mutation submission. Fresh collections are removed after evidence collection; server processes remain running, so caches are not cold-reset between trials.

The matrix has three engines × four profiles × five independently initialized trials = 60 planned runs. A seeded shuffle determines the whole run order. Backend trials run serially. Failures remain in the inventory and are not replaced by a successful retry. A modified protocol requires a new experiment directory and source snapshot.

## Observation rule

A monotonic client clock defines submission, actual write start, write acknowledgement, and each read's start/response. Readers are dispatched before the writer so they can observe successful visibility before an acknowledgement. Acknowledgement semantics differ by backend: Qdrant `wait=true`, Weaviate synchronous indexing, and PostgreSQL autocommit with READ COMMITTED on independent connections. These are recorded configurations, not equivalent durability guarantees.

Two independent channels inspect each operation:

| Operation | Direct-ID channel | Unfiltered top-10 vector-search channel |
|---|---|---|
| Insert | Requested ID has version 1 | Requested ID has version 1 using its new vector |
| Replacement | Same ID has version 1 | Same ID has version 1 using its replacement vector |
| Delete | ID is absent | ID is absent when searching with its old vector |

A negative approximate-neighbor result alone never confirms deletion. Replacement preconditions prevent an already-retrievable old-vector hit from trivially satisfying the new-vector query.

For each channel, three consecutive correct responses must span at least 50ms. A false response or read error resets that channel's sequence. Negative responses are followed after at least 10ms; positive responses after at least 25ms. These are gaps after responses, not fixed-frequency samples. A confirmed channel stops polling. Thus regression counts concern only observations before confirmation; the protocol does not prove permanent visibility or a shared simultaneous 50ms window across channels.

`first_observed_ms` is the later of the first correct response on each channel, conditional on eventual successful confirmation. It means both channels have shown the target state by that point, not that both were sampled at the same instant. `confirmed_ms` is the later channel confirmation. Success additionally requires the writer to finish without error before the event deadline. Responses received after the deadline remain raw evidence and cannot establish success. Pending writes/read requests are drained before final artifact collection.

The event deadline and finite API timeouts bound observation, not transaction cancellation: a database may complete a timed-out write. Report errors and timeouts as outcomes, not fabricated five-second latency values. Timing samples are observation upper bounds; subtracting an acknowledgement timestamp can be negative and does not estimate pure indexing lag.

## Concurrent quality

Independent background traffic cycles through the 100 real questions. It searches only the immutable cohort within the same mutable collection. Exact normalized cosine top-10 references are computed before measurement. ANN recall@10 credits unique returned corpus IDs whose score is at least the tenth reference score minus 1e-6, avoiding arbitrary tie penalties. This filtered workload is distinct from unfiltered mutation self-vector probes.

Report ANN recall and semantic nDCG@10 separately. nDCG uses the dataset judgments and the transformed subset. Also report the exact-vector nDCG, which exposes embedding/retrieval limits independently of ANN approximation. Failed background queries contribute zero quality in the overall mean; latency distributions include successful requests, with errors reported separately.

## Configuration and resource evidence

All engines use cosine similarity, HNSW construction parameter 128, connectivity 16, and search effort 128. Equal parameter values do not imply identical algorithms. Weaviate uses REST writes and GraphQL search; Qdrant uses pooled HTTP REST; PostgreSQL uses psycopg connections per worker. Transport and client-library differences remain part of the measured interface.

Each reference container has two virtual CPUs and 3 GiB memory, with swapping beyond that limit disabled. PostgreSQL has 1 GiB shared memory available and 512 MiB index-build maintenance memory. Immutable image digests, effective server versions/configuration, Docker VM resources, host model/memory, package versions, and cgroup CPU/throttling/memory counters are recorded. Local Docker Desktop shares physical hardware with the client and other host activity. These data do not constitute an isolated cloud-hardware study.

The client uses four write workers, 32 observer workers, four quality-query workers, and a 1,024-active-event limit. Measurement overhead is intentionally exposed through probe counts, service times, dispatch delays, and idle-versus-loaded query latency. That comparison includes both mutation and observer traffic; it does not identify the causal write-only slowdown.

## Validity and statistics

A run passes only if all eight checks hold:

1. p95 mutation admission lag ≤ the shortest requested interarrival interval.
2. p95 probe dispatch lag ≤ 10ms.
3. p95 quality-query dispatch lag ≤ its requested interarrival interval.
4. Mean ANN recall@10 ≥95% both at idle and under load.
5. No invalid mutation preconditions.
6. No mutation client-capacity drops.
7. No out-of-cohort background results.
8. HNSW configuration/readiness/query-plan checks pass.

A comparison group qualifies only when all five planned trials complete and pass. A failed gate does not erase evidence. Database errors/timeouts remain in the all-offered reliability denominator even when timing gates pass. Setup failures remain failed planned trials with no invented event samples. Do not compare a limited cell as though its p95 were a qualified engine latency.

For each operation, report success rate, conditional first/confirmed p50/p95/p99, acknowledgement and search-minus-ack distributions, observed regressions, and fractions confirmed within 100ms and 1s. The latter two use all offered operations. Query quality and latency accompany freshness results. A low conditional p95 with poor reliability is not a win.

The primary cross-trial statistic is the median of trial p95s. A seeded percentile bootstrap samples whole trials with replacement 5,000 times and reports a 95% interval. Never treat individual operations as independent experimental replicates. Five trials provide coarse uncertainty estimates; overlapping/nonoverlapping intervals are not a significance test. There is no combined score or global winner.

## Calibration, reproducibility, and related work

Known-delay controls inject 0, 25, and 100ms visibility delay, plus an independent 100ms acknowledgement delay. The verifier checks no state is reported before its injected delay and that visibility can precede acknowledgement. Unit tests cover stale versions, deletion false positives, confirmation resets, deadline handling, and evidence tampering. These controls validate harness behavior, not server/network overhead.

Each experiment preserves exact launch source, package/image/data fingerprints, randomized run order, configuration, every terminal event, every probe outcome (including errors and late observations), background query IDs/results/quality, and summaries. `verify_v2.py` reconstructs confirmations, distributions, counts, and validity gates from evidence; `--check-data` additionally recomputes quality using the measured cache. File checksums provide integrity, not independent authentication. A second independent hardware/operator replication remains future work.

[ANN-Benchmarks](https://github.com/erikbern/ann-benchmarks) studies recall/performance; [VectorDBBench](https://github.com/zilliztech/VectorDBBench) includes ingestion and readiness workloads; [FreshDiskANN](https://arxiv.org/abs/2105.09613) studies concurrent changes and retrieval; [BEIR](https://github.com/beir-cellar/beir) supplies diverse real retrieval tasks. This benchmark packages version-aware API observations, quality checks, and auditable evidence into a reproducible comparison workflow. It makes no novelty-first claim.

The earlier insert-only protocol remains [archived separately](docs/insert-v1-methodology.md), and its results must not be pooled with protocol 2.
