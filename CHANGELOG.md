# Changes

## 0.5.0 — mixed-mutation visibility v2

- Add independently scheduled direct and vector readers, version-aware replacement and deletion rules, known-delay controls, and bounded confirmation.
- Add SciFact and Natural Questions with real test questions, exact ANN references, semantic nDCG, pinned sources, and licensed cache manifests.
- Add 4k/10k/100k workloads, steady and burst arrivals, shared resource limits, effective index checks, and randomized repeated trials.
- Preserve errors, timeouts, client limitations, CPU/throttling counters, raw query/probe evidence, and exact launch source.
- Add an independent evidence verifier and fault-injection tests.
- Add a static interactive website with filters, uncertainty intervals, quality/validity details, individual-trial inspection, and portable downloads.
- Retain protocol 1 as historical evidence; its results are not pooled with protocol 2.

## 0.4.0 — insert visibility v1

- Add a real Python documentation corpus with deterministic sampling, source hashes, retained licensing and pinned local semantic embeddings.
- Add a randomized publication matrix, independent trial aggregation, failure-inclusive SLO fractions, trial bootstrap intervals and exportable CDF figures.
- Use monotonic elapsed times and one-request-at-a-time probe scheduling, with submission-relative deadlines and raw per-probe evidence.
- Expose collection-wide retrieval so preloads participate in search.
- Use PostgreSQL connections per worker; fail on HNSW creation errors and refuse destructive Qdrant dimension changes.
- Pin tested images by digest and standardize container CPU/memory limits.
- Add source/config/dependency provenance, artifact checksums, an evidence verifier, CI, citation metadata and an explicit publication protocol.

The historical pack remains a smoke suite with synthetic vectors and templated text. Its results are not interchangeable with protocol v1 results.
