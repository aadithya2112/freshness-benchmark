from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .models import BenchmarkConfig, BenchmarkPackConfig, CompareConfig


def _default_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _add_shared_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--docs", type=int, default=200)
    parser.add_argument("--rate", type=float, default=5.0)
    parser.add_argument("--collection", default="freshness_benchmark")
    parser.add_argument("--backend", choices=["qdrant", "weaviate", "pgvector"], default="qdrant")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--weaviate-url", default="http://localhost:8080")
    parser.add_argument(
        "--pgvector-dsn",
        default=os.getenv(
            "PGVECTOR_DSN",
            "postgresql://postgres:postgres@localhost:5432/freshness",
        ),
    )
    parser.add_argument("--embedding-mode", choices=["live", "precomputed"], default="precomputed")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--embedding-dimensions", type=int, default=128)
    parser.add_argument("--embedding-concurrency", type=int, default=4)
    parser.add_argument("--write-concurrency", type=int, default=4)
    parser.add_argument("--search-concurrency", type=int, default=8)
    parser.add_argument(
        "--workload",
        choices=["synthetic-small", "synthetic-medium", "synthetic-large", "dataset"],
        default="synthetic-medium",
    )
    parser.add_argument("--dataset-path", default=None)
    parser.add_argument("--dataset-format", choices=["jsonl", "text-dir"], default=None)
    parser.add_argument("--text-field", default=None)
    parser.add_argument("--id-field", default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--poll-interval-ms", type=int, default=250)
    parser.add_argument("--max-wait-s", type=int, default=120)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freshness-benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run freshness latency benchmark")
    _add_shared_run_arguments(run_parser)
    run_parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to ./artifacts/<run-id>",
    )
    run_parser.add_argument("--run-id", default=None)

    report_parser = subparsers.add_parser(
        "report",
        help="Generate an HTML report from benchmark artifacts",
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

    compare_parser = subparsers.add_parser(
        "compare",
        help="Run a comparison matrix across backends and rates",
    )
    _add_shared_run_arguments(compare_parser)
    compare_parser.add_argument("--compare-id", default=None)
    compare_parser.add_argument(
        "--backends",
        nargs="+",
        default=["qdrant", "weaviate", "pgvector"],
    )
    compare_parser.add_argument("--rates", nargs="+", type=float, default=[2.0, 5.0, 10.0])
    compare_parser.add_argument(
        "--embedding-modes",
        nargs="+",
        default=["precomputed"],
    )
    compare_parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to ./artifacts/<compare-id>",
    )

    pack_parser = subparsers.add_parser(
        "pack",
        help="Run pinned benchmark-pack presets with repeated trials",
    )
    pack_parser.add_argument("--pack-id", default=None)
    pack_parser.add_argument(
        "--presets",
        nargs="+",
        choices=[
            "baseline_docs_precomputed",
            "baseline_synthetic_precomputed",
            "embedding_reality_check",
        ],
        default=[
            "baseline_docs_precomputed",
            "baseline_synthetic_precomputed",
        ],
    )
    pack_parser.add_argument("--trials", type=int, default=3)
    pack_parser.add_argument("--collection", default="freshness_benchmark")
    pack_parser.add_argument("--qdrant-url", default="http://localhost:6333")
    pack_parser.add_argument("--weaviate-url", default="http://localhost:8080")
    pack_parser.add_argument(
        "--pgvector-dsn",
        default=os.getenv(
            "PGVECTOR_DSN",
            "postgresql://postgres:postgres@localhost:5432/freshness",
        ),
    )
    pack_parser.add_argument("--provider", default="openrouter")
    pack_parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    pack_parser.add_argument("--embedding-model", default="text-embedding-3-small")
    pack_parser.add_argument("--embedding-dimensions", type=int, default=128)
    pack_parser.add_argument("--embedding-concurrency", type=int, default=4)
    pack_parser.add_argument("--write-concurrency", type=int, default=4)
    pack_parser.add_argument("--search-concurrency", type=int, default=8)
    pack_parser.add_argument("--top-k", type=int, default=10)
    pack_parser.add_argument("--poll-interval-ms", type=int, default=250)
    pack_parser.add_argument("--max-wait-s", type=int, default=120)
    pack_parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to ./artifacts/<pack-id>",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    run_id = args.run_id or _default_id("run")
    model = os.getenv("OPENROUTER_MODEL", args.embedding_model)
    out_dir = args.out_dir or str(Path("artifacts") / run_id)

    cfg = BenchmarkConfig(
        run_id=run_id,
        docs=args.docs,
        rate=args.rate,
        collection=args.collection,
        backend=args.backend,
        qdrant_url=args.qdrant_url.rstrip("/"),
        weaviate_url=args.weaviate_url.rstrip("/"),
        pgvector_dsn=args.pgvector_dsn,
        embedding_mode=args.embedding_mode,
        embedding_model=model,
        provider=args.provider,
        base_url=args.base_url.rstrip("/"),
        embedding_dimensions=args.embedding_dimensions,
        top_k=args.top_k,
        poll_interval_ms=args.poll_interval_ms,
        max_wait_s=args.max_wait_s,
        embedding_concurrency=args.embedding_concurrency,
        write_concurrency=args.write_concurrency,
        search_concurrency=args.search_concurrency,
        workload=args.workload,
        dataset_path=args.dataset_path,
        dataset_format=args.dataset_format,
        text_field=args.text_field,
        id_field=args.id_field,
        out_dir=out_dir,
    )
    cfg.validate()
    return cfg


def compare_config_from_args(args: argparse.Namespace) -> CompareConfig:
    compare_id = args.compare_id or _default_id("compare")
    base_run = config_from_args(
        argparse.Namespace(
            run_id=f"{compare_id}-seed",
            out_dir=str(Path("artifacts") / compare_id / "runs" / "seed"),
            **{
                "docs": args.docs,
                "rate": args.rate,
                "collection": args.collection,
                "backend": args.backend,
                "qdrant_url": args.qdrant_url,
                "weaviate_url": args.weaviate_url,
                "pgvector_dsn": args.pgvector_dsn,
                "embedding_mode": args.embedding_mode,
                "embedding_model": args.embedding_model,
                "provider": args.provider,
                "base_url": args.base_url,
                "embedding_dimensions": args.embedding_dimensions,
                "embedding_concurrency": args.embedding_concurrency,
                "write_concurrency": args.write_concurrency,
                "search_concurrency": args.search_concurrency,
                "workload": args.workload,
                "dataset_path": args.dataset_path,
                "dataset_format": args.dataset_format,
                "text_field": args.text_field,
                "id_field": args.id_field,
                "top_k": args.top_k,
                "poll_interval_ms": args.poll_interval_ms,
                "max_wait_s": args.max_wait_s,
            },
        )
    )
    out_dir = args.out_dir or str(Path("artifacts") / compare_id)
    compare_cfg = CompareConfig(
        compare_id=compare_id,
        backends=list(args.backends),
        rates=list(args.rates),
        embedding_modes=list(args.embedding_modes),
        base_run_config=replace(base_run, out_dir=str(Path(out_dir) / "runs" / "seed")),
        out_dir=out_dir,
    )
    compare_cfg.validate()
    return compare_cfg


def pack_config_from_args(args: argparse.Namespace) -> BenchmarkPackConfig:
    pack_id = args.pack_id or _default_id("pack")
    out_dir = args.out_dir or str(Path("artifacts") / pack_id)
    model = os.getenv("OPENROUTER_MODEL", args.embedding_model)
    base_run = BenchmarkConfig(
        run_id=f"{pack_id}-seed",
        docs=1,
        rate=1.0,
        collection=args.collection,
        backend="qdrant",
        qdrant_url=args.qdrant_url.rstrip("/"),
        weaviate_url=args.weaviate_url.rstrip("/"),
        pgvector_dsn=args.pgvector_dsn,
        embedding_mode="precomputed",
        embedding_model=model,
        provider=args.provider,
        base_url=args.base_url.rstrip("/"),
        embedding_dimensions=args.embedding_dimensions,
        top_k=args.top_k,
        poll_interval_ms=args.poll_interval_ms,
        max_wait_s=args.max_wait_s,
        embedding_concurrency=args.embedding_concurrency,
        write_concurrency=args.write_concurrency,
        search_concurrency=args.search_concurrency,
        workload="synthetic-medium",
        dataset_path=None,
        dataset_format=None,
        text_field=None,
        id_field=None,
        out_dir=str(Path(out_dir) / "seed"),
    )
    base_run.validate()
    cfg = BenchmarkPackConfig(
        pack_id=pack_id,
        presets=list(args.presets),
        trials=args.trials,
        base_run_config=base_run,
        out_dir=out_dir,
    )
    cfg.validate()
    return cfg
