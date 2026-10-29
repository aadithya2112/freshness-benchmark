# Reproduce the insert visibility release

Python 3.12, `uv`, and Docker are the tested environment. Allow approximately 1 GB for Python/model dependencies plus container images and generated data. Preparation downloads public data and model weights; timed runs need no embedding API key.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[publication]'
docker compose up -d
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/prepare_publication_data.py
.venv/bin/python scripts/run_publication.py --out artifacts/my-publication
.venv/bin/python scripts/analyze_publication.py artifacts/my-publication
.venv/bin/python scripts/verify_publication.py artifacts/my-publication
.venv/bin/python scripts/bundle_publication.py artifacts/my-publication
```

The output directory must be new: overwriting benchmark evidence is refused. The matrix may take several minutes. Compare `benchmarks/python-docs.lock.json` with the generated manifest before accepting new results. The preparation script verifies source/corpus hashes; regenerated vector hashes may vary across hardware, and must be reported.

For exact dependency replication, use `benchmarks/publication-requirements.txt` with Python 3.12. Model weights are pinned by revision; the generated cache records the actual output hash. For exact vector comparisons distribute the generated corpus/cache with `PYTHON-LICENSE.txt`, the model attribution and the manifest. The checked-in lock records the reference hashes. No third-party corpus is silently assigned the repository's code license.

Artifacts:

- `REPORT.md`, `results.csv`, `results.json`: scoped findings, reliability, uncertainty and validity gates.
- `freshness.svg`, `freshness.png`: exportable CDF figure with all submissions in the denominator.
- `experiment.json`: randomized order, data manifest, dependency versions, container settings.
- `source.tar.gz`: source used at launch, including uncommitted implementation changes.
- `runs/*`: complete JSONL traces, CSV metrics, JSON summary, HTML report.
- `checksums.json`: SHA-256 inventory of the final evidence directory.

A public release should include this evidence directory plus the generated data/cache and retained licenses. Use the provided local release bundle when present. Read `methodology.md` before interpreting results. Initial results cover one documentation corpus and one small populated-index size; stronger cross-domain or production-scale claims require additional result series.

For a quick functional check, reduce the matrix explicitly; label it a smoke test:

```sh
.venv/bin/python scripts/run_publication.py --out artifacts/my-smoke --trials 1 --docs 20 --preload 100 --rates 50
```

Consult `experiment.json` whenever custom parameters are used. A smoke run is not a valid publication submission.
