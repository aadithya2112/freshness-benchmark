from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import CompareRow, CompareSummary, DocLifecycle, RunSummary


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if pct <= 0:
        return min(values)
    if pct >= 100:
        return max(values)
    sorted_vals = sorted(values)
    rank = (len(sorted_vals) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    if low == high:
        return sorted_vals[low]
    frac = rank - low
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * frac


def metric_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "min": min(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
    }


def summarize(
    *,
    records: list[DocLifecycle],
    config: dict[str, Any],
    backend_info: dict[str, Any],
    environment: dict[str, Any],
    started_at: str,
    finished_at: str,
    wall_clock_s: float,
    actual_submission_rate: float,
    actual_completion_rate: float,
) -> RunSummary:
    docs_total = len(records)
    docs_success = sum(1 for r in records if r.status == "success")
    docs_timeout = sum(1 for r in records if r.status == "timeout")
    docs_error = sum(1 for r in records if r.status == "error")
    success_rate = (docs_success / docs_total) if docs_total else 0.0

    freshness_vals = [r.freshness_ms for r in records if r.freshness_ms is not None]
    embedding_vals = [r.embedding_ms for r in records if r.embedding_ms is not None]
    write_vals = [r.write_ack_ms for r in records if r.write_ack_ms is not None]
    visibility_vals = [r.visibility_ms for r in records if r.visibility_ms is not None]

    run_id = str(config["run_id"])
    return RunSummary(
        run_id=run_id,
        backend=str(config["backend"]),
        embedding_mode=str(config["embedding_mode"]),
        workload=str(config["workload"]),
        dataset=config.get("dataset_path")
        and {
            "mode": "dataset",
            "path": config.get("dataset_path"),
            "format": config.get("dataset_format"),
            "text_field": config.get("text_field"),
            "id_field": config.get("id_field"),
        }
        or None,
        docs_total=docs_total,
        docs_success=docs_success,
        docs_timeout=docs_timeout,
        docs_error=docs_error,
        success_rate=success_rate,
        freshness_ms=metric_stats(freshness_vals),
        embedding_ms=metric_stats(embedding_vals),
        write_ack_ms=metric_stats(write_vals),
        visibility_ms=metric_stats(visibility_vals),
        requested_rate=float(config["rate"]),
        actual_submission_rate=actual_submission_rate,
        actual_completion_rate=actual_completion_rate,
        wall_clock_s=wall_clock_s,
        started_at=started_at,
        finished_at=finished_at,
        backend_info=backend_info,
        environment=environment,
        config=config,
    )


def compare_row_from_summary(
    *,
    compare_id: str,
    summary: RunSummary,
    rate: float,
    run_dir: str,
) -> CompareRow:
    return CompareRow(
        compare_id=compare_id,
        run_id=summary.run_id,
        backend=summary.backend,
        embedding_mode=summary.embedding_mode,
        workload=summary.workload,
        rate=rate,
        docs_total=summary.docs_total,
        docs_success=summary.docs_success,
        docs_timeout=summary.docs_timeout,
        docs_error=summary.docs_error,
        success_rate=summary.success_rate,
        freshness_p50_ms=summary.freshness_ms["p50"],
        freshness_p95_ms=summary.freshness_ms["p95"],
        embedding_p50_ms=summary.embedding_ms["p50"],
        write_ack_p50_ms=summary.write_ack_ms["p50"],
        visibility_p50_ms=summary.visibility_ms["p50"],
        actual_submission_rate=summary.actual_submission_rate,
        actual_completion_rate=summary.actual_completion_rate,
        run_dir=run_dir,
    )


def write_trace_jsonl(path: Path, records: list[DocLifecycle]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec.to_record(), ensure_ascii=True) + "\n")


def write_metrics_csv(path: Path, records: list[DocLifecycle]) -> None:
    fieldnames = [
        "run_id",
        "backend",
        "embedding_mode",
        "workload",
        "doc_id",
        "doc_num",
        "source_ref",
        "status",
        "error",
        "search_attempts",
        "vector_dimensions",
        "t_submitted",
        "t_embedding_done",
        "t_write_acked",
        "t_searchable",
        "embedding_ms",
        "write_ack_ms",
        "visibility_ms",
        "freshness_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = rec.to_record()
            writer.writerow({k: row.get(k) for k in fieldnames})


def write_summary_json(path: Path, summary: RunSummary) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(summary), f, indent=2)


def write_compare_csv(path: Path, rows: list[CompareRow]) -> None:
    fieldnames = list(rows[0].to_record().keys()) if rows else [
        "compare_id",
        "run_id",
        "backend",
        "embedding_mode",
        "workload",
        "rate",
        "docs_total",
        "docs_success",
        "docs_timeout",
        "docs_error",
        "success_rate",
        "freshness_p50_ms",
        "freshness_p95_ms",
        "embedding_p50_ms",
        "write_ack_p50_ms",
        "visibility_p50_ms",
        "actual_submission_rate",
        "actual_completion_rate",
        "run_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_record())


def write_compare_summary_json(path: Path, summary: CompareSummary) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(summary), f, indent=2)


def print_summary(summary: RunSummary) -> None:
    print(f"run_id={summary.run_id} backend={summary.backend} embedding_mode={summary.embedding_mode}")
    if summary.dataset:
        print(
            "dataset mode={mode} format={format} path={path}".format(
                mode=summary.dataset.get("mode"),
                format=summary.dataset.get("format"),
                path=summary.dataset.get("path"),
            )
        )
    print(
        "docs_total={docs_total} docs_success={docs_success} docs_timeout={docs_timeout} "
        "docs_error={docs_error} success_rate={success_rate:.3f}".format(
            docs_total=summary.docs_total,
            docs_success=summary.docs_success,
            docs_timeout=summary.docs_timeout,
            docs_error=summary.docs_error,
            success_rate=summary.success_rate,
        )
    )
    print(
        "freshness_ms min={min} p50={p50} p95={p95} p99={p99} max={max}".format(
            **summary.freshness_ms,
        )
    )
    print(
        "embedding_ms p50={p50} p95={p95} write_ack_ms p50={write_p50} p95={write_p95} visibility_ms p50={vis_p50} p95={vis_p95}".format(
            p50=summary.embedding_ms["p50"],
            p95=summary.embedding_ms["p95"],
            write_p50=summary.write_ack_ms["p50"],
            write_p95=summary.write_ack_ms["p95"],
            vis_p50=summary.visibility_ms["p50"],
            vis_p95=summary.visibility_ms["p95"],
        )
    )
    print(
        "requested_rate={requested:.2f} actual_submission_rate={submitted:.2f} actual_completion_rate={completed:.2f} wall_clock_s={wall:.2f}".format(
            requested=summary.requested_rate,
            submitted=summary.actual_submission_rate,
            completed=summary.actual_completion_rate,
            wall=summary.wall_clock_s,
        )
    )
