# Reproducing and publishing protocol 2

Use [the README commands](../README.md#run) with [the normative protocol](../methodology.md). The reference image digests and limits are in `docker-compose.v2.yml`; data hashes are in `benchmarks/{nq,scifact}-v2.lock.json`. The default matrix is the reference protocol. Shorter runs, different rates, or subsets are pilots/custom experiments, and must be labelled as such.

## Reference artifacts

The website's Reproduce page provides:

- `benchmark-source.zip`: maintained source, tests, protocol, documentation, and website code.
- `experiment-source.tar.gz`: the exact source captured when the measurement process launched.
- `benchmark-evidence.tar.gz`: the complete measurement directory, including calibration traces and failed runs, suitable for offline verification.
- `results.json` and `results.csv`: aggregate comparisons plus provenance.
- `evidence/<run>-<file>.gz`: individual summaries, mutation records, query records, probe traces, and exact-reference metadata.
- `checksums.json`: a SHA-256 inventory of public downloads. Integrity checks do not authenticate the publisher.

See [data attribution and terms](DATA-NOTICE.md). The GitHub release additionally distributes the exact cached dataset/vector files used for reference measurements, preserving their upstream licenses. These avoid device-dependent floating-point regeneration. Download and extract them at the repository root so `benchmarks/data/v2/{scifact,nq}/manifest.json` exists. Do not mix caches from different preparations.

## Verify

```sh
tar -xzf benchmark-evidence.tar.gz
.venv/bin/python scripts/verify_v2.py publication-v2
# Also check retrieval quality against the exact measured cache:
.venv/bin/python scripts/verify_v2.py publication-v2 --check-data
```

The verifier rejects missing trials, mismatched identities, changed launch source, inconsistent status totals, confirmations without adequate raw evidence, latency/statistic mismatches, incorrect validity labels, impossible acknowledgement timestamps, cardinality mismatches after acknowledged mutations, and broken calibration. A report with failed gates can still verify successfully: honest evidence of a limitation is not an integrity failure. With `--check-data`, the local cache must match the measured manifest; query quality and exact references are recomputed.

For an actively running experiment, `--allow-partial` audits the completed prefix. That output must not be presented as a complete reference release. Artifact summaries and release reports are generated only after data collection. No failed final run is silently substituted or rerun in place.

## Run on a different host

Start the versioned containers with the dedicated Compose project and localhost ports. The provided PostgreSQL password is only for these local benchmark containers; no deployment service is exposed publicly. The runner creates/drops only its `fb2_` namespace. Other containers/data are not cleared.

Prepare datasets outside measurement, close other compute-heavy work, and ensure all three services are ready. Do not run benchmark matrices concurrently. The reference uses Python 3.12 and Apple M4/Docker Desktop; a different architecture or OS is a new hardware track even if image digests match. Compare within each matched track, and publish its full resource metadata.

Data preparation uses a pinned model and archive checksums. `--device cpu` is portable; `--device mps` reproduces the reference preparation device category, but does not guarantee bitwise equality across framework/OS releases. The measured manifest is the authority. The runner verifies normalized finite arrays before use.

Each matrix directory must be new. To diagnose a failure, use a separate pilot directory. Changing `SCENARIOS`, HNSW configuration, consistency settings, hardware limits, query cohort, or observation parameters defines a new declared configuration. Record the reason and retain old evidence.

## Build and preview the website

```sh
.venv/bin/python scripts/build_website.py artifacts/my-v2
python3 -m http.server 4173 --bind 127.0.0.1 --directory website/dist
```

The canonical UI sources are in `web/`; generated output and the separate hosting checkout are ignored under `website/`. Buildless HTML/CSS/JS can be hosted by any static server. Results are loaded from generated JSON. Filters are encoded in the URL, charts expose the same values as the accessible result table, and trial dialogs link to compressed evidence. There are no fabricated example scores or client-side result submissions.

The public site is generated from one experiment at a time. Community results require review and independent replication before being called verified. Do not combine hardware tracks or protocol versions into a single unqualified leaderboard.

## Pilot decisions retained

Before freezing the reference matrix, pilots revealed a rejected Qdrant full-scan threshold, PostgreSQL's Docker shared-memory default, excessive observer traffic, and client queues under a 120 mutation/s burst. The final protocol uses a supported threshold, explicit shared memory, three spaced positive observations, and a common 10 mutation/s baseline with 40/s bursts. These choices were made before the final trials, apply to every engine, and define the tested scope. The higher-rate pilot is an observer-limited diagnostic, not evidence of a database's maximum throughput. Pilot artifacts are retained separately from the reference results.

## Limits and next research tracks

A public benchmark release is not the same as a peer-reviewed comparative study. This release provides a runnable protocol and auditable local reference. Valuable follow-up tracks include independently operated hosts, distributed replicas/read consistency, multi-million-vector corpora, long-running churn on reused IDs, historical change streams, additional embedding models/domains, and matched-recall tuning curves. Those require new evidence; none is implied by this release.

## Interrupted experiments

`resume_streaming.py` can continue a stopped matrix only after verifying the
completed prefix, unchanged measurement code, cache manifests, package versions,
Docker host, image digests, and resource limits. Completed or failed terminal
trials are never replaced. A partial trial without a terminal record is archived
under `continuations/`, with its reason and raw partial traces, then restarted
from a fresh collection. Additional known-delay controls are retained for each
continuation. These interrupted attempts are disclosed separately and are not
counted as successful or failed database operations.

The reference includes one such continuation after a host/session interruption
and container restart. Its first six completed trials were retained; the partial
seventh trial was archived and restarted. Treat the continuation history as part
of the experiment provenance, including possible cache/host-state differences.
