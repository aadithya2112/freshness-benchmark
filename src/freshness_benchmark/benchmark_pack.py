from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .models import (
    BenchmarkPackConfig,
    BenchmarkPackRow,
    BenchmarkPackRun,
    BenchmarkPackSummary,
    CompareConfig,
    CompareRow,
    now_utc,
)
from .reporting import (
    percentile,
    write_benchmark_pack_csv,
    write_benchmark_pack_summary_json,
)
from .runner import BackendFactory, EmbeddingSourceFactory, run_compare
from .visualize import generate_benchmark_pack_html_report


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_PACK_PATH = _REPO_ROOT / "benchmarks" / "corpora" / "docs_pack.jsonl"


def available_benchmark_pack_presets() -> dict[str, dict[str, Any]]:
    docs_pack_path = str(_DOCS_PACK_PATH)
    return {
        "baseline_docs_precomputed": {
            "description": "Docs-style corpus across all three local vector backends in precomputed mode.",
            "docs": 60,
            "backends": ["qdrant", "weaviate", "pgvector"],
            "rates": [2.0, 5.0, 10.0],
            "embedding_modes": ["precomputed"],
            "workload": "dataset",
            "dataset_path": docs_pack_path,
            "dataset_format": "jsonl",
            "text_field": "body",
            "id_field": "doc_id",
            "embedding_model": "text-embedding-3-small",
        },
        "baseline_synthetic_precomputed": {
            "description": "Synthetic medium workload across all three local vector backends in precomputed mode.",
            "docs": 60,
            "backends": ["qdrant", "weaviate", "pgvector"],
            "rates": [2.0, 5.0, 10.0],
            "embedding_modes": ["precomputed"],
            "workload": "synthetic-medium",
            "dataset_path": None,
            "dataset_format": None,
            "text_field": None,
            "id_field": None,
            "embedding_model": "text-embedding-3-small",
        },
        "embedding_reality_check": {
            "description": "Pinned live-embedding run on the docs-style corpus to show real embedding contribution.",
            "docs": 24,
            "backends": ["qdrant"],
            "rates": [2.0],
            "embedding_modes": ["live"],
            "workload": "dataset",
            "dataset_path": docs_pack_path,
            "dataset_format": "jsonl",
            "text_field": "body",
            "id_field": "doc_id",
            "embedding_model": "text-embedding-3-small",
        },
    }


def _preset_compare_config(
    config: BenchmarkPackConfig,
    *,
    preset_name: str,
    trial: int,
) -> CompareConfig:
    presets = available_benchmark_pack_presets()
    if preset_name not in presets:
        raise ValueError(f"Unsupported benchmark-pack preset: {preset_name}")
    preset = presets[preset_name]
    compare_id = f"{config.pack_id}-{preset_name}-t{trial}"
    compare_dir = Path(config.out_dir) / "presets" / preset_name / f"trial-{trial}"
    base_run = replace(
        config.base_run_config,
        run_id=f"{compare_id}-seed",
        docs=int(preset["docs"]),
        collection=config.base_run_config.collection,
        backend=preset["backends"][0],
        embedding_mode=preset["embedding_modes"][0],
        embedding_model=str(preset["embedding_model"]),
        workload=str(preset["workload"]),
        dataset_path=preset["dataset_path"],
        dataset_format=preset["dataset_format"],
        text_field=preset["text_field"],
        id_field=preset["id_field"],
        out_dir=str(compare_dir / "runs" / "seed"),
    )
    base_run.validate()
    compare_config = CompareConfig(
        compare_id=compare_id,
        backends=list(preset["backends"]),
        rates=list(preset["rates"]),
        embedding_modes=list(preset["embedding_modes"]),
        base_run_config=base_run,
        out_dir=str(compare_dir),
    )
    compare_config.validate()
    return compare_config


def _median(values: list[float | None]) -> float | None:
    normalized = [value for value in values if value is not None]
    if not normalized:
        return None
    return percentile(normalized, 50)


def _aggregate_rows(
    *,
    pack_id: str,
    preset_names: list[str],
    trial_runs: list[BenchmarkPackRun],
    trial_rows: dict[tuple[str, int], list[CompareRow]],
) -> list[BenchmarkPackRow]:
    grouped: dict[tuple[str, str, str, str, float], list[tuple[str, CompareRow]]] = {}
    for preset_name in preset_names:
        for trial_run in [run for run in trial_runs if run.preset == preset_name]:
            rows = trial_rows[(preset_name, trial_run.trial)]
            for row in rows:
                key = (preset_name, row.backend, row.embedding_mode, row.workload, row.rate)
                grouped.setdefault(key, []).append((trial_run.compare_id, row))

    aggregated: list[BenchmarkPackRow] = []
    for key, entries in sorted(grouped.items()):
        preset_name, backend, embedding_mode, workload, rate = key
        sample = entries[0][1]
        aggregated.append(
            BenchmarkPackRow(
                pack_id=pack_id,
                preset=preset_name,
                backend=backend,
                embedding_mode=embedding_mode,
                workload=workload,
                rate=rate,
                docs_total=sample.docs_total,
                trials=len(entries),
                median_success_rate=_median([entry.success_rate for _, entry in entries]),
                median_freshness_p50_ms=_median([entry.freshness_p50_ms for _, entry in entries]),
                median_freshness_p95_ms=_median([entry.freshness_p95_ms for _, entry in entries]),
                median_embedding_p50_ms=_median([entry.embedding_p50_ms for _, entry in entries]),
                median_write_ack_p50_ms=_median([entry.write_ack_p50_ms for _, entry in entries]),
                median_visibility_p50_ms=_median([entry.visibility_p50_ms for _, entry in entries]),
                median_actual_submission_rate=_median(
                    [entry.actual_submission_rate for _, entry in entries]
                ),
                median_actual_completion_rate=_median(
                    [entry.actual_completion_rate for _, entry in entries]
                ),
                trial_compare_ids=[compare_id for compare_id, _ in entries],
            )
        )
    return aggregated


def run_benchmark_pack(
    config: BenchmarkPackConfig,
    *,
    backend_factory: BackendFactory | None = None,
    embedding_source_factory: EmbeddingSourceFactory | None = None,
) -> BenchmarkPackSummary:
    pack_dir = Path(config.out_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    trial_runs: list[BenchmarkPackRun] = []
    trial_rows: dict[tuple[str, int], list[CompareRow]] = {}
    for preset_name in config.presets:
        for trial in range(1, config.trials + 1):
            compare_config = _preset_compare_config(config, preset_name=preset_name, trial=trial)
            compare_kwargs: dict[str, Any] = {}
            if backend_factory is not None:
                compare_kwargs["backend_factory"] = backend_factory
            if embedding_source_factory is not None:
                compare_kwargs["embedding_source_factory"] = embedding_source_factory
            compare_summary = run_compare(compare_config, **compare_kwargs)
            trial_run = BenchmarkPackRun(
                preset=preset_name,
                trial=trial,
                compare_id=compare_config.compare_id,
                compare_dir=str(Path(compare_config.out_dir)),
            )
            trial_runs.append(trial_run)
            trial_rows[(preset_name, trial)] = list(compare_summary.rows)

    rows = _aggregate_rows(
        pack_id=config.pack_id,
        preset_names=config.presets,
        trial_runs=trial_runs,
        trial_rows=trial_rows,
    )
    presets = available_benchmark_pack_presets()
    summary = BenchmarkPackSummary(
        pack_id=config.pack_id,
        generated_at=now_utc().isoformat(),
        rows=rows,
        trial_runs=trial_runs,
        config={
            "trials": config.trials,
            "presets": [
                {"name": preset_name, **presets[preset_name]}
                for preset_name in config.presets
            ],
            "base_run_config": {**asdict(config.base_run_config), "pgvector_dsn": "[redacted]"},
        },
    )
    write_benchmark_pack_summary_json(pack_dir / "benchmark_pack.json", summary)
    write_benchmark_pack_csv(pack_dir / "benchmark_pack.csv", rows)
    generate_benchmark_pack_html_report(
        benchmark_pack_json=pack_dir / "benchmark_pack.json",
        out_file=pack_dir / "benchmark_pack.html",
    )
    return summary
