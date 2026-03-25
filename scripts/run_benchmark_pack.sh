#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHONPATH=src python3 -m freshness_benchmark.cli pack "$@"
