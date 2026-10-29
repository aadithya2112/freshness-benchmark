# Contributing results and backends

Use [protocol 2](methodology.md) and [the reproduction guide](docs/publication-v2.md). Identify the protocol and configuration in every submission. Include complete raw evidence, data/model/cache hashes, source snapshot, dependencies, image digests, hardware limits, and every planned trial, including failures. Disclose tuning, transport, consistency, durability, replication, and host activity. Screenshots and aggregate CSVs alone are insufficient.

Run `scripts/verify_v2.py` on the complete experiment, with `--check-data` when the measured cache is available. A passing verifier establishes completeness/internal consistency, not independent authentication or replication. Community submissions remain unverified until independently reproduced. Preserve failed validity gates visibly and do not pool different hardware or quality tracks.

For a new protocol-2 backend, extend `StreamingBackend` with create, bulk, finish_load, write, get, search, count, info, drop, and close behavior. Use dedicated benchmark namespaces. Implement both independent direct-ID reads and actual vector search, stable IDs, application versions, all three mutations, and immutable-cohort filtering. Search cannot be replaced by an ID fetch. Retain effective configuration and actual query-plan/index evidence. Never silently fall back to a different index after setup failure.

Test stale versions, negative ANN deletion false positives, errors, late responses, resource cleanup, and adapter request semantics. Run known-delay calibration and real-data smoke trials before a final matrix. A new mutation type, historical stream, filter type, quality target, or consistency mode needs a declared success oracle and a separately labelled track.

Keep website content derived from exported evidence. Do not hardcode scores, omit failed trials, claim statistical significance from five-trial intervals, or call local reference results universal rankings. Cite upstream data and related benchmarks, and preserve their licenses.
