# Functional Document

## Document Control

- Project: Freshness Benchmark
- Version: Review Draft 1.0
- Date: March 26, 2026
- Status: Feature complete for core scope, polish and presentation work remaining
- Intended audience: Review panel, engineering leads, QA reviewers

## 1. Overview

Freshness Benchmark is a Python-based command-line application used to measure how quickly a newly submitted document becomes searchable in a vector database. The system is designed to benchmark vector-search freshness across multiple backends under controlled and repeatable workloads.

The primary business question answered by the tool is:

`How long does it take for a document to become searchable after submission?`

The benchmark captures that answer through the headline metric:

`freshness_ms = t_searchable - t_submitted`

In addition, the tool records intermediate timing stages so engineers can identify whether latency is dominated by embedding generation, backend write acknowledgement, or search visibility delay.

## 2. Objectives

- Provide a repeatable local benchmarking workflow for vector-search freshness.
- Compare multiple vector backends under equivalent conditions.
- Separate backend-only latency from end-to-end ingest latency.
- Generate reviewer-friendly artifacts in JSON, CSV, and HTML formats.
- Support both synthetic workloads and local dataset-backed workloads.

## 3. Target Users

- Engineers evaluating vector database freshness behavior.
- Reviewers validating benchmark completeness and reproducibility.
- QA and platform teams performing smoke validation before demonstrations.
- Project stakeholders who need HTML reports and comparison summaries.

## 4. Current Functional Scope

The current implementation supports the following major capabilities:

### 4.1 Supported Commands

| Command | Purpose | Outcome |
| --- | --- | --- |
| `run` | Execute one freshness benchmark run | Creates a run folder with trace, metrics, summary, and HTML report |
| `compare` | Execute a matrix of runs across backends, rates, and embedding modes | Creates comparison JSON, CSV, and HTML outputs plus nested run artifacts |
| `pack` | Execute pinned benchmark-pack presets over repeated trials | Creates aggregated benchmark-pack JSON, CSV, and HTML outputs |
| `report` | Regenerate an HTML report from a previous run directory | Rebuilds `report.html` from stored artifacts |

### 4.2 Supported Backends

- Qdrant
- Weaviate
- pgvector on PostgreSQL

### 4.3 Supported Embedding Modes

- `precomputed`
  - Uses deterministic vectors to isolate backend behavior and support fair comparisons.
- `live`
  - Uses live embedding generation to measure true end-to-end ingest freshness.

### 4.4 Supported Workload Types

- `synthetic-small`
- `synthetic-medium`
- `synthetic-large`
- `dataset`
  - JSONL corpus
  - Text or Markdown directory corpus

## 5. Functional Behavior

### 5.1 Single Benchmark Run

For a single run, the user selects a backend, embedding mode, rate, document count, and workload. The system then:

1. Creates a run identifier and output directory.
2. Loads or generates the workload documents.
3. Generates embeddings or looks up deterministic vectors.
4. Writes the document and vector payload to the selected backend.
5. Polls the backend until the expected document becomes searchable.
6. Writes run artifacts and renders an HTML report.

### 5.2 Comparison Matrix

The comparison workflow expands a base configuration into multiple runs across:

- one or more backends
- one or more submission rates
- one or more embedding modes

The system aggregates the resulting summaries into a comparison table and renders a visual HTML dashboard for cross-run analysis.

### 5.3 Benchmark Pack

The benchmark-pack workflow provides pinned presets intended for repeatable review and presentation scenarios. The current preset family includes:

- `baseline_docs_precomputed`
- `baseline_synthetic_precomputed`
- `embedding_reality_check`

Each preset runs for a configurable number of trials and aggregates median values across the trial set for reviewer-friendly output.

### 5.4 Report Regeneration

The report workflow allows a previously generated run to be rendered again as HTML without rerunning the benchmark itself. This supports review and presentation refreshes after artifact creation.

## 6. Inputs And Validation Rules

### 6.1 Common Runtime Inputs

The system accepts, among others, the following major inputs:

- document count
- submission rate
- collection name
- backend selection
- backend endpoint or DSN
- embedding mode
- embedding model and provider settings
- workload type
- concurrency settings
- polling interval and timeout
- output directory

### 6.2 Dataset-Specific Inputs

When workload is `dataset`, the system requires:

- `dataset_path`
- `dataset_format`
- `text_field` for JSONL datasets
- optional `id_field`

The system validates that:

- numeric values are greater than zero where required
- backend names are supported
- embedding modes are supported
- dataset arguments are only supplied for dataset runs
- dataset paths exist and match the requested format
- required dataset fields are present and non-empty

Invalid input causes the CLI to terminate with an error rather than producing incomplete artifacts.

## 7. Data And Artifact Outputs

### 7.1 Single Run Outputs

Each run generates the following files under `artifacts/<run-id>/`:

- `trace.jsonl`
- `metrics.csv`
- `summary.json`
- `report.html`

### 7.2 Comparison Outputs

Each comparison generates:

- `comparison.json`
- `comparison.csv`
- `comparison.html`
- nested run folders under `runs/<run-id>/`

### 7.3 Benchmark Pack Outputs

Each benchmark pack generates:

- `benchmark_pack.json`
- `benchmark_pack.csv`
- `benchmark_pack.html`
- preset trial folders under `presets/<preset>/trial-<n>/`

## 8. Core Metrics

The system records the following measurements:

- `embedding_ms`
- `write_ack_ms`
- `visibility_ms`
- `freshness_ms`

Reported statistics include:

- minimum
- p50
- p95
- p99
- maximum

The headline review metric remains `freshness_ms`.

## 9. Dataset Handling Rules

For dataset-based runs, the system injects a deterministic retrieval anchor into the indexed copy of each document. This enables a consistent backend-agnostic success rule and improves benchmark repeatability. The original source text is preserved separately in trace metadata for reviewability and auditability.

Supported dataset sources are:

- JSONL records
- text files
- Markdown files

## 10. Dependencies And Environment

### 10.1 Runtime Dependencies

- Python 3.10 or newer
- Docker
- Local Qdrant, Weaviate, and PostgreSQL services for full backend coverage

### 10.2 Credential Requirements

API credentials are only required for `live` embedding mode. The project currently supports configuration through provider settings and environment variables.

## 11. Non-Functional Expectations

- Reproducible local execution for review and smoke validation
- Bounded concurrency for embedding, write, and search stages
- Clear artifact generation for post-run analysis
- Backend comparability in `precomputed` mode
- HTML output suitable for internal presentation and review

## 12. Current Project Status

The project is in a late-stage state. Core functionality is implemented and the principal benchmarking workflows are available end to end. The remaining work is primarily finishing work rather than feature development.

Completed or effectively complete areas:

- CLI workflow coverage for run, compare, pack, and report
- backend adapter coverage for the three intended local backends
- workload support for synthetic and dataset-backed scenarios
- per-run and aggregated artifact generation
- unit test coverage around runner, pack aggregation, and workload behavior

Remaining polish-focused items:

- tighten reviewer-facing wording in generated HTML reports
- complete broader smoke runs across all local backends for presentation confidence
- perform final documentation cleanup and formatting alignment
- finalize review collateral and evidence packaging

## 13. Assumptions And Constraints

- The tool is intended for local or controlled benchmark environments rather than hosted multi-tenant deployment.
- The benchmark measures freshness through search visibility, not semantic relevance quality.
- Live-mode results depend on external embedding provider latency and credentials.
- Local backend availability is assumed when full comparison workflows are executed.

## 14. Acceptance View For Review

For Review 2, the product should be considered acceptable if:

- all four CLI workflows operate as documented
- required artifacts are produced in the expected locations
- supported backends can be benchmarked under the intended local setup
- reports and summaries provide sufficient data for reviewer interpretation
- remaining gaps are limited to presentation polish, regression breadth, and documentation cleanup
