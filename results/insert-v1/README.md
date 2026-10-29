# Reference results — insert visibility v1

See [REPORT.md](REPORT.md) for the full scope and [results.csv](results.csv) for machine-readable aggregates. These are local Apple M4 / Docker Desktop measurements, not vendor-certified results. The exact host and Docker configuration, dependency versions, randomized order and data hashes are in [experiment.json](experiment.json).

All 30 planned trials completed: five trials for each backend/rate cell and 30,000 measured inserts. All insert observations succeeded; every cell passed the specified client scheduling and probe gates. The artifact verifier also checked record counts, status accounting, stage timing consistency, probe evidence and input hashes.

Full raw evidence is retained locally at `artifacts/publication-v1/`. The portable `artifacts/publication-v1-release.tar.gz` bundle includes raw traces, exact data/cache, licenses and source, with a companion SHA-256 file. Attach that bundle when publishing these reference results. To regenerate, follow [the reproduction guide](../../docs/publication.md).

The lower observed latencies at 200 versus 50 documents/s should be interpreted cautiously: this is a client-observed response metric. Fixed-interval arrivals, OS wakeups, connection activity and backend execution can influence it. The experiment does not establish a causal explanation or an exact internal visibility delay.
