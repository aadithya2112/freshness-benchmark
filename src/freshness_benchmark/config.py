from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import BenchmarkConfig


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freshness-benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run freshness latency benchmark")
    run_parser.add_argument("--docs", type=int, default=200)
    run_parser.add_argument("--rate", type=float, default=5.0)
    run_parser.add_argument("--collection", default="freshness_benchmark")
    run_parser.add_argument("--qdrant-url", default="http://localhost:6333")
    run_parser.add_argument("--embedding-model", default="text-embedding-3-small")
    run_parser.add_argument("--provider", default="openrouter")
    run_parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    run_parser.add_argument("--top-k", type=int, default=10)
    run_parser.add_argument("--poll-interval-ms", type=int, default=250)
    run_parser.add_argument("--max-wait-s", type=int, default=120)
    run_parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to ./artifacts/<run-id>",
    )
    run_parser.add_argument("--run-id", default=None)

    report_parser = subparsers.add_parser(
        "report",
        help="Generate a single-page HTML report from benchmark artifacts",
    )
    report_parser.add_argument(
        "--run-dir",
        default=None,
        help="Run directory containing summary.json and metrics.csv. Defaults to latest run in --artifacts-dir.",
    )
    report_parser.add_argument(
        "--artifacts-dir",
        default="artifacts",
        help="Directory containing run folders (default: artifacts).",
    )
    report_parser.add_argument(
        "--out-file",
        default=None,
        help="Output HTML file path. Defaults to <run-dir>/report.html.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    run_id = args.run_id or _default_run_id()
    model = os.getenv("OPENROUTER_MODEL", args.embedding_model)
    out_dir = args.out_dir or str(Path("artifacts") / run_id)

    cfg = BenchmarkConfig(
        run_id=run_id,
        docs=args.docs,
        rate=args.rate,
        collection=args.collection,
        qdrant_url=args.qdrant_url.rstrip("/"),
        embedding_model=model,
        provider=args.provider,
        base_url=args.base_url.rstrip("/"),
        top_k=args.top_k,
        poll_interval_ms=args.poll_interval_ms,
        max_wait_s=args.max_wait_s,
        out_dir=out_dir,
    )
    cfg.validate()
    return cfg
