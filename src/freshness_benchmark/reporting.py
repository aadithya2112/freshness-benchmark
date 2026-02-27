from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import DocLifecycle, RunSummary


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


def summarize(run_id: str, records: list[DocLifecycle], config: dict[str, Any]) -> RunSummary:
    docs_total = len(records)
    docs_success = sum(1 for r in records if r.status == "success")
    docs_timeout = sum(1 for r in records if r.status == "timeout")
    docs_error = sum(1 for r in records if r.status == "error")
    success_rate = (docs_success / docs_total) if docs_total else 0.0

    freshness_vals = [r.freshness_ms for r in records if r.freshness_ms is not None]
    embedding_vals = [r.embedding_ms for r in records if r.embedding_ms is not None]
    index_vals = [r.index_ack_ms for r in records if r.index_ack_ms is not None]

    return RunSummary(
        run_id=run_id,
        docs_total=docs_total,
        docs_success=docs_success,
        docs_timeout=docs_timeout,
        docs_error=docs_error,
        success_rate=success_rate,
        freshness_ms=metric_stats(freshness_vals),
        embedding_ms=metric_stats(embedding_vals),
        index_ack_ms=metric_stats(index_vals),
        config=config,
    )


def write_trace_jsonl(path: Path, records: list[DocLifecycle]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec.to_record(), ensure_ascii=True) + "\n")


def write_metrics_csv(path: Path, records: list[DocLifecycle]) -> None:
    fieldnames = [
        "run_id",
        "doc_id",
        "status",
        "error",
        "t_ingested",
        "t_embedding_done",
        "t_index_update_done",
        "t_first_search_success",
        "embedding_ms",
        "index_ack_ms",
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


def print_summary(summary: RunSummary) -> None:
    print(f"run_id={summary.run_id}")
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
        "embedding_ms p50={p50} p95={p95}".format(
            p50=summary.embedding_ms["p50"],
            p95=summary.embedding_ms["p95"],
        )
    )
    print(
        "index_ack_ms p50={p50} p95={p95}".format(
            p50=summary.index_ack_ms["p50"],
            p95=summary.index_ack_ms["p95"],
        )
    )
