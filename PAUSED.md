# Paused checkpoint — 29 October 2026

The user requested a temporary pause. Do not restart work until asked to continue.

The reference matrix stopped cleanly after **44 of 60 trials**. All completed
trials passed their validity gates. The evidence audit verified 14,100 mutations,
13,200 background queries, and 106,533 probes. Sixteen trials remain in the
original randomized order. This pause did not interrupt a trial.

- Evidence: `artifacts/publication-v2/` (including `PAUSED.json` and `verification.json`).
- Portable checkpoint: `artifacts/publication-v2-paused.tar.gz` and its `.sha256` file.
- Exact data caches: `benchmarks/data/v2/`. Keep these and `.venv` unchanged.
- Updated local website: `website/dist/`, explicitly labelled as paused.
- Canonical minimal website sources: `web/`.
- Branch: `publish/mixed-mutations-v2`.
- Draft PR: https://github.com/aadithya2112/freshness-benchmark/pull/1
- All 57 automated tests passed; Linux real-backend compatibility smoke passed.
- The three benchmark containers and local preview server are stopped.

## Resume when requested

From the repository root, start the existing pinned containers and wait for their
readiness endpoints. Do not recreate the Python environment, re-encode the data,
change measurement files, or rerun completed trials in place.

```sh
docker start freshness-v2-qdrant freshness-v2-weaviate freshness-v2-pgvector
curl -fsS http://127.0.0.1:16333/readyz
curl -fsS http://127.0.0.1:18080/v1/.well-known/ready
docker exec freshness-v2-pgvector pg_isready -U postgres -d freshness
caffeinate -i .venv/bin/python scripts/resume_streaming.py artifacts/publication-v2
```

The resume helper checks source/environment/cache hashes, keeps all completed
trials, records this pause in continuation history, repeats calibration, and
continues the remaining matrix. Keep it in a retained execution session. If an
environment check fails, investigate; do not bypass it or substitute new results.

## Work remaining after the matrix

1. Run the full deep evidence audit (`--check-data`) and replace the partial
   verification report. Generate the final report and plots using the commands
   in `docs/publication-v2.md`.
2. Commit final small results under `results/mixed-v2/`, rebuild the website, and
   package the release. Retain the separate Linux compatibility evidence at
   `artifacts/linux-smoke-v2/` and diagnostic pilots.
3. Validate final website/download flows, publish GitHub release `v0.5.0`, and
   publish the public website. Nothing has been deployed or released yet.
4. Update the README/PR with actual live links, finish CI, and merge the release
   changes. Remove this paused-work note when work resumes/completes.

The existing Sites project is `appgprj_6ae230d718c08191a711db89d6662ab4`, with its
separate checkout at `website/` and manifest at `website/.openai/hosting.json`.
It is currently private and unpublished. Reuse it; do not create another site.
Obtain a fresh source credential through Sites and follow its source helper
and save/deploy workflow. Credentials must remain in memory and hidden stdin.

The earlier host/session interruption after six completed trials remains
disclosed under `continuations/`; its partial seventh attempt was preserved.
Update the report's continuation wording to include this later clean pause.
The eventual release is a single-host reference, not an independent performance
replication or universal ranking.
