> Historical development notes. For the current public comparison protocol, see [methodology.md](methodology.md) and [docs/publication.md](docs/publication.md).

# Freshness Benchmark: Detailed Project Explanation

## 1. Project Overview

This project is a benchmarking system for **vector database freshness**, meaning the time it takes for a newly ingested document or vector to become retrievable through search.

In many modern retrieval systems, especially Retrieval-Augmented Generation (RAG) systems, semantic search applications, and vector-based recommendation engines, it is not enough for a database to merely store a vector successfully. What often matters operationally is this:

**After a document is submitted, how long does it take before the system can actually find it through search?**

That question is the central problem this project solves.

The project is implemented as a Python command-line application that can:

- run a single freshness benchmark
- compare multiple vector backends under the same workload
- generate reports and visual summaries
- execute pinned benchmark packs for repeatable evaluation

The currently supported vector backends are:

- Qdrant
- Weaviate
- pgvector on PostgreSQL

The benchmark supports both:

- **precomputed embeddings**, to isolate backend behavior fairly
- **live embeddings**, to measure true end-to-end ingest latency


## 2. The Problem Being Solved

### 2.1 Why freshness matters

In a vector search system, the write path and the search path are often not identical in timing behavior.

A vector may be:

- accepted by the API
- written to storage
- acknowledged as a successful write
- but still not yet visible to nearest-neighbor search

This delay can happen for many reasons:

- index maintenance is asynchronous
- visibility to search is delayed behind internal buffering
- graph or ANN structures must be updated
- backend-specific ingestion pipelines may separate persistence from search exposure
- embedding generation itself may add latency upstream

So the user-visible question is not simply:

“Did the write succeed?”

It is:

“Can the application retrieve the new content yet?”

That is particularly important in systems where fresh data must become searchable quickly, for example:

- newly uploaded documents in an enterprise search system
- customer support knowledge bases
- event-driven RAG systems
- continuously updated recommendation feeds
- monitoring or incident-response systems


### 2.2 Why existing measurements are often insufficient

Many performance evaluations focus on:

- throughput
- indexing speed
- query latency
- storage cost

Those are important, but they do not directly answer the freshness question.

A system can have:

- fast write acknowledgements
- fast query latency
- but still poor freshness if newly ingested vectors are not visible immediately

This project addresses that gap by measuring **ingest-to-search latency** explicitly.


### 2.3 The large-index motivation

An important refinement emerged during the project:

freshness should not only be measured in an almost-empty database.

In real systems, vector databases are usually already populated with a large amount of data. In that situation, ingesting new vectors may become slower because the backend must update indexes or graph structures while already managing a substantial corpus.

To address that more realistic scenario, the project now supports a **large-index freshness mode** using `--preload-docs`, which preloads setup documents into the same backend before the benchmarked documents are measured.


## 3. Core Benchmark Question

The primary benchmark question is:

> How long does it take for a newly submitted document to become searchable?

The main metric is:

`freshness_ms = t_searchable - t_submitted`

This metric is intentionally user-centric. It measures the elapsed time between:

- the moment the benchmark submits a document for processing
- and the first moment the backend can return that same document through search


## 4. Secondary Metrics

To make the result diagnostically useful, the project also records intermediate stage timings:

- `embedding_ms = t_embedding_done - t_submitted`
- `write_ack_ms = t_write_acked - t_embedding_done`
- `visibility_ms = t_searchable - t_write_acked`

These secondary metrics help explain where time is being spent:

- `embedding_ms` captures embedding generation cost
- `write_ack_ms` captures backend write and acknowledgement behavior
- `visibility_ms` captures how long it takes after the backend acknowledges the write for the document to become searchable

This decomposition is valuable because it prevents the benchmark from becoming a black-box stopwatch.


## 5. Design Goals

The project was designed around the following goals:

1. **Measure search freshness directly**
   The project must answer the question of search visibility, not just write success.

2. **Compare backends fairly**
   The same workload should be executable across multiple vector databases under equivalent conditions.

3. **Separate backend behavior from embedding-provider behavior**
   Live embedding services introduce latency and network variance, so the project must support a deterministic mode that isolates backend-only behavior.

4. **Remain reproducible**
   Runs should emit stable artifacts that can be reviewed later.

5. **Be explainable**
   The benchmark should produce enough metadata, traces, and summary outputs that results are auditable rather than anecdotal.


## 6. High-Level Solution

The solution is a **pipelined benchmarking CLI** with a backend abstraction layer and reproducible workloads.

At a high level, the system works like this:

1. Load or generate benchmark documents.
2. Convert each document into a vector, either deterministically or using a live provider.
3. Upsert the document and vector into a chosen backend.
4. Poll the backend until that exact document becomes retrievable by vector search.
5. Record timing data and write artifacts.
6. Optionally compare multiple backends or rates and render reports.


## 7. Why the Runner Is Pipelined

An important architectural choice is that the benchmark is **not strictly serial**.

Instead of processing document 1 fully before starting document 2, the runner overlaps multiple stages:

- embedding
- writing
- search polling

This is closer to how real ingestion pipelines behave in production. It also allows the benchmark to represent the effects of:

- target ingest rate
- bounded concurrency
- queueing between stages
- overlapping writes and search visibility delays

If everything were processed serially, the benchmark would under-represent contention and would produce less realistic freshness behavior under load.


## 8. Main Components

### 8.1 CLI layer

The CLI exposes four main workflows:

- `run`: execute one benchmark run
- `compare`: execute a matrix across backends, rates, and embedding modes
- `pack`: run predefined benchmark presets repeatedly
- `report`: regenerate HTML reports from prior artifacts


### 8.2 Configuration and validation

The project validates:

- document counts
- submission rates
- concurrency settings
- backend selection
- dataset arguments
- timeout and polling settings

This is important because benchmark output is only meaningful if the input configuration is internally consistent.


### 8.3 Workload loader

The workload system supports:

- `synthetic-small`
- `synthetic-medium`
- `synthetic-large`
- `dataset`

Dataset mode supports:

- JSONL corpora
- text or Markdown directories

The workload loader is responsible for turning source material into `WorkloadDoc` records with:

- a document id
- benchmark text
- source text
- a deterministic retrieval anchor
- a source reference


### 8.4 Embedding source abstraction

The benchmark supports two embedding modes:

- `precomputed`
- `live`

In `precomputed` mode, vectors are deterministic and local. This removes external API latency and makes backend comparisons fairer.

In `live` mode, vectors are produced through a real embedding provider. This gives a more realistic end-to-end latency measurement but is less controlled.


### 8.5 Backend adapter abstraction

The project uses a backend contract so the runner does not need backend-specific logic everywhere.

Each backend implements:

- `prepare_run(vector_size)`
- `upsert(point_id, vector, payload)`
- `search(vector, limit)`
- `reset_run_data()`
- `backend_info()`
- `close()`

This abstraction lets the project benchmark Qdrant, Weaviate, and pgvector through one common execution pipeline while preserving backend-specific implementation details inside adapters.


### 8.6 Reporting layer

The project generates several artifact types:

- `trace.jsonl`
- `metrics.csv`
- `summary.json`
- `report.html`

Comparison workflows additionally generate:

- `comparison.json`
- `comparison.csv`
- `comparison.html`

Benchmark-pack workflows produce aggregated pack outputs in JSON, CSV, and HTML.


## 9. Deterministic Retrieval Anchors

One subtle problem in benchmarking vector search freshness is this:

How does the benchmark know that the backend has returned the correct document?

If the benchmark relied only on semantic similarity of arbitrary text, then results would become entangled with ranking quality rather than freshness. That would make the benchmark less repeatable and less backend-agnostic.

To solve this, the project injects a deterministic retrieval anchor into the benchmarked copy of each document. This gives each document a unique marker that supports consistent retrieval validation.

This design choice is important because it separates:

- **freshness of search visibility**
from
- **semantic ranking quality**

The benchmark is therefore intentionally measuring visibility, not relevance quality.


## 10. Measurement Methodology

For each measured document, the lifecycle is:

1. The document is scheduled according to the configured target ingest rate.
2. The embedding is generated or looked up.
3. The document and vector are upserted into the backend.
4. The write acknowledgement timestamp is recorded.
5. The system repeatedly queries the backend using the document’s vector.
6. Once the correct document appears in the result set, the searchable timestamp is recorded.

The benchmark then computes per-document latency metrics and aggregates them into:

- min
- p50
- p95
- p99
- max

Using percentiles is important because freshness behavior is often not uniform. A system may have a good median but poor tail latency, and tail behavior is often what matters operationally.


## 11. Fairness Strategy

The benchmark uses `precomputed` mode as its primary fairness baseline.

This matters because live embedding mode introduces uncontrolled variation from:

- network latency
- provider performance
- API throttling
- embedding model behavior

With precomputed vectors, the benchmark more accurately isolates backend behavior such as:

- write acknowledgement latency
- search visibility latency
- indexing side effects

This is essential if the purpose is comparing backends rather than comparing a whole application stack.


## 12. Large-Index Freshness Mode

### 12.1 Motivation

Originally, the benchmark was strongest at measuring freshness of newly ingested documents in a relatively small or fresh benchmark corpus. However, an important practical question is:

> What happens when the backend already contains a large amount of data?

In real deployments, new writes are usually not entering an empty database. Index maintenance costs may grow, and backend behavior may change significantly when the collection is already large.


### 12.2 Solution

The project now supports `--preload-docs`.

When this option is used:

1. The benchmark first loads a preload corpus from the same workload source.
2. Those preload documents are embedded and written into the same backend collection, table, or class.
3. The preload documents use a separate logical run id such as `<run_id>__preload`.
4. The measured phase then starts and benchmarks only the subsequent `--docs` documents.

This gives a benchmark that simulates:

- an already-populated backend
- followed by measurement of freshness for new writes


### 12.3 Why preload documents are excluded from metrics

The preload data is setup state, not benchmark target data.

The measured freshness numbers should describe only the documents that are intentionally being benchmarked. Therefore:

- preload writes are not included in `metrics.csv`
- preload writes do not contribute to freshness percentiles
- preload behavior is recorded only as summary metadata


### 12.4 Why measured search still filters by run id

A key design decision is that even in large-index mode, the visibility poll still searches only for the **measured run’s** documents.

This is deliberate.

The goal is to answer:

“How does ingest freshness behave when the physical backend is already large?”

not:

“How does retrieval quality or mixed-corpus ranking behave across the entire combined corpus?”

That keeps the benchmark focused and prevents the result from being polluted by unrelated retrieval interactions with the preload corpus.


## 13. Comparison and Benchmark-Pack Workflows

The project does more than run one isolated experiment.

### 13.1 Compare workflow

The `compare` workflow expands one base configuration into a matrix across:

- multiple backends
- multiple ingest rates
- multiple embedding modes

This makes it possible to answer questions such as:

- Which backend has lower p95 freshness at 10 docs/s?
- How much does live embedding inflate end-to-end latency?
- Does one backend degrade faster as ingest rate rises?


### 13.2 Benchmark-pack workflow

The `pack` workflow runs pinned benchmark presets repeatedly so the output is suitable for review or presentation.

This is useful because one run can be noisy. Repeated trials and median aggregation make results more defensible.


## 14. Artifacts and Why They Matter

The project emphasizes auditability.

### 14.1 `trace.jsonl`

This stores raw per-document lifecycle records. It is useful for detailed debugging and post hoc validation.

### 14.2 `metrics.csv`

This provides a tabular representation of per-document latency metrics. It is convenient for spreadsheet analysis or external plotting.

### 14.3 `summary.json`

This contains the aggregated run result, backend metadata, environment metadata, and now preload metadata where applicable.

### 14.4 HTML reports

The HTML reports make the benchmark easier to review by people who may not want to inspect raw JSON or CSV files directly.

These artifacts are important academically and operationally because they allow:

- reproducibility
- verification
- communication of results


## 15. Technical Strengths of the Project

This project has several strong engineering characteristics:

### 15.1 Clear separation of concerns

The runner, workload loader, backend adapters, embedding sources, and reporting logic are separated cleanly.

### 15.2 Reproducibility

The benchmark can be rerun locally with deterministic inputs in precomputed mode.

### 15.3 Backend portability

The abstraction layer allows consistent methodology across different vector backends.

### 15.4 Interpretability

The split into embedding, write acknowledgement, visibility, and freshness stages makes results explainable.

### 15.5 Practical realism

The addition of large-index preload mode makes the benchmark more representative of real deployment conditions.


## 16. Limitations

No benchmark is universal, and this one also has clear scope boundaries.

### 16.1 It does not measure semantic quality

This project is about freshness and visibility, not retrieval quality, ranking quality, or answer usefulness in a downstream RAG application.

### 16.2 It is primarily for controlled/local environments

The project is designed for controlled benchmarking, not production deployment as a service.

### 16.3 Live mode includes external noise

When live embeddings are used, the result includes variability from external services.

### 16.4 Large-index mode is still scoped

The preload mode simulates ingest into a large backend, but it intentionally does not try to measure full-corpus retrieval behavior as a second benchmark objective.


## 17. What Was Built in This Project

From an implementation perspective, the project now includes:

- a Python CLI for benchmark execution and reporting
- synthetic and dataset-backed workload generation
- deterministic anchor injection for reproducible retrieval validation
- deterministic and live embedding modes
- backend adapters for Qdrant, Weaviate, and pgvector
- single-run, comparison, and benchmark-pack workflows
- JSON, CSV, and HTML artifact generation
- a large-index freshness mode using preload documents
- automated tests covering workload behavior, runner behavior, reporting, and adapter contracts


## 18. Why This Project Is Useful

This project is useful because it turns an operationally important but often vague question into a measurable, reproducible benchmark:

**How fresh is my vector search system after ingest?**

It is valuable for:

- engineering evaluation of vector databases
- system design decisions in RAG pipelines
- benchmarking backend behavior under controlled workloads
- identifying whether bottlenecks come from embeddings, writing, or visibility delay
- studying how ingestion behaves when the backend is already populated

In short, the project provides both:

- a practical tool for backend evaluation
- and a methodological framework for reasoning about vector-search freshness rigorously


## 19. Concluding Explanation

If this project were summarized in one sentence for a technical reviewer, it would be:

> Freshness Benchmark is a reproducible Python benchmarking framework that measures how long it takes for newly ingested vectors to become searchable across multiple vector backends, while separating embedding cost, write acknowledgement cost, and search visibility delay, and now also supporting measurement under large preloaded corpus conditions.

That combination of measurement clarity, backend comparability, and realistic ingest scenarios is the main contribution of the project.
