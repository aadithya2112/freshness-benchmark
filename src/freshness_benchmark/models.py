from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.isoformat()


def delta_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds() * 1000.0


@dataclass
class BenchmarkConfig:
    run_id: str
    docs: int
    rate: float
    collection: str
    backend: str
    qdrant_url: str
    weaviate_url: str
    pgvector_dsn: str | None
    embedding_mode: str
    embedding_model: str
    provider: str
    base_url: str
    embedding_dimensions: int
    top_k: int
    poll_interval_ms: int
    max_wait_s: int
    embedding_concurrency: int
    write_concurrency: int
    search_concurrency: int
    workload: str
    dataset_path: str | None
    dataset_format: str | None
    text_field: str | None
    id_field: str | None
    out_dir: str

    def validate(self) -> None:
        if self.docs <= 0:
            raise ValueError("--docs must be > 0")
        if self.rate <= 0:
            raise ValueError("--rate must be > 0")
        if self.top_k <= 0:
            raise ValueError("--top-k must be > 0")
        if self.poll_interval_ms <= 0:
            raise ValueError("--poll-interval-ms must be > 0")
        if self.max_wait_s <= 0:
            raise ValueError("--max-wait-s must be > 0")
        if self.embedding_dimensions <= 0:
            raise ValueError("--embedding-dimensions must be > 0")
        if self.embedding_concurrency <= 0:
            raise ValueError("--embedding-concurrency must be > 0")
        if self.write_concurrency <= 0:
            raise ValueError("--write-concurrency must be > 0")
        if self.search_concurrency <= 0:
            raise ValueError("--search-concurrency must be > 0")
        if self.embedding_mode not in {"live", "precomputed"}:
            raise ValueError("--embedding-mode must be 'live' or 'precomputed'")
        if self.backend not in {"qdrant", "weaviate", "pgvector"}:
            raise ValueError("--backend must be one of qdrant, weaviate, pgvector")
        if self.workload not in {
            "synthetic-small",
            "synthetic-medium",
            "synthetic-large",
            "dataset",
        }:
            raise ValueError("--workload must be a supported synthetic profile or dataset")
        if not self.collection:
            raise ValueError("--collection must not be empty")
        if self.embedding_mode == "live" and not self.embedding_model:
            raise ValueError("--embedding-model must not be empty in live mode")
        if self.backend == "pgvector" and not self.pgvector_dsn:
            raise ValueError("--pgvector-dsn is required when --backend pgvector")

        dataset_args = (
            self.dataset_path,
            self.dataset_format,
            self.text_field,
            self.id_field,
        )
        if self.workload == "dataset":
            if not self.dataset_path:
                raise ValueError("--dataset-path is required when --workload dataset")
            if not self.dataset_format:
                raise ValueError("--dataset-format is required when --workload dataset")
            if self.dataset_format not in {"jsonl", "text-dir"}:
                raise ValueError("--dataset-format must be 'jsonl' or 'text-dir'")
            dataset_path = Path(self.dataset_path)
            if not dataset_path.exists():
                raise ValueError(f"--dataset-path does not exist: {self.dataset_path}")
            if self.dataset_format == "jsonl":
                if not dataset_path.is_file():
                    raise ValueError("--dataset-path must be a file for --dataset-format jsonl")
                if not self.text_field:
                    raise ValueError("--text-field is required for --dataset-format jsonl")
            if self.dataset_format == "text-dir" and not dataset_path.is_dir():
                raise ValueError("--dataset-path must be a directory for --dataset-format text-dir")
        else:
            if any(value is not None for value in dataset_args):
                raise ValueError(
                    "--dataset-path, --dataset-format, --text-field, and --id-field are only valid when --workload dataset"
                )

    def dataset_metadata(self) -> dict[str, Any] | None:
        if self.workload != "dataset":
            return None
        return {
            "mode": "dataset",
            "path": self.dataset_path,
            "format": self.dataset_format,
            "text_field": self.text_field,
            "id_field": self.id_field,
        }


@dataclass
class CompareConfig:
    compare_id: str
    backends: list[str]
    rates: list[float]
    embedding_modes: list[str]
    base_run_config: BenchmarkConfig
    out_dir: str

    def validate(self) -> None:
        if not self.backends:
            raise ValueError("--backends must include at least one backend")
        if not self.rates:
            raise ValueError("--rates must include at least one rate")
        if not self.embedding_modes:
            raise ValueError("--embedding-modes must include at least one mode")
        for backend in self.backends:
            if backend not in {"qdrant", "weaviate", "pgvector"}:
                raise ValueError(f"Unsupported backend in compare config: {backend}")
        for rate in self.rates:
            if rate <= 0:
                raise ValueError("--rates entries must be > 0")
        for mode in self.embedding_modes:
            if mode not in {"live", "precomputed"}:
                raise ValueError(
                    "--embedding-modes entries must be 'live' or 'precomputed'"
                )


@dataclass
class WorkloadDoc:
    doc_num: int
    doc_id: str
    text: str
    source_text: str
    anchor: str
    source_ref: str | None = None


@dataclass
class DocLifecycle:
    run_id: str
    backend: str
    embedding_mode: str
    workload: str
    doc_id: str
    doc_num: int
    text: str
    source_text: str | None = None
    source_ref: str | None = None
    t_submitted: datetime | None = None
    t_embedding_done: datetime | None = None
    t_write_acked: datetime | None = None
    t_searchable: datetime | None = None
    freshness_ms: float | None = None
    embedding_ms: float | None = None
    write_ack_ms: float | None = None
    visibility_ms: float | None = None
    status: str = "pending"
    error: str | None = None
    search_attempts: int = 0
    vector_dimensions: int | None = None

    def finalize_metrics(self) -> None:
        self.embedding_ms = delta_ms(self.t_submitted, self.t_embedding_done)
        self.write_ack_ms = delta_ms(self.t_embedding_done, self.t_write_acked)
        self.visibility_ms = delta_ms(self.t_write_acked, self.t_searchable)
        self.freshness_ms = delta_ms(self.t_submitted, self.t_searchable)

    def mark_timeout(self, reason: str) -> None:
        self.status = "timeout"
        self.error = reason
        self.finalize_metrics()

    def mark_error(self, reason: str) -> None:
        self.status = "error"
        self.error = reason
        self.finalize_metrics()

    def mark_success(self) -> None:
        self.status = "success"
        self.error = None
        self.finalize_metrics()

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["t_submitted"] = to_iso(self.t_submitted)
        record["t_embedding_done"] = to_iso(self.t_embedding_done)
        record["t_write_acked"] = to_iso(self.t_write_acked)
        record["t_searchable"] = to_iso(self.t_searchable)
        return record


@dataclass
class RunSummary:
    run_id: str
    backend: str
    embedding_mode: str
    workload: str
    dataset: dict[str, Any] | None
    docs_total: int
    docs_success: int
    docs_timeout: int
    docs_error: int
    success_rate: float
    freshness_ms: dict[str, float | None]
    embedding_ms: dict[str, float | None]
    write_ack_ms: dict[str, float | None]
    visibility_ms: dict[str, float | None]
    requested_rate: float
    actual_submission_rate: float
    actual_completion_rate: float
    wall_clock_s: float
    started_at: str
    finished_at: str
    backend_info: dict[str, Any]
    environment: dict[str, Any]
    config: dict[str, Any]


@dataclass
class CompareRow:
    compare_id: str
    run_id: str
    backend: str
    embedding_mode: str
    workload: str
    rate: float
    docs_total: int
    docs_success: int
    docs_timeout: int
    docs_error: int
    success_rate: float
    freshness_p50_ms: float | None
    freshness_p95_ms: float | None
    embedding_p50_ms: float | None
    write_ack_p50_ms: float | None
    visibility_p50_ms: float | None
    actual_submission_rate: float
    actual_completion_rate: float
    run_dir: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompareSummary:
    compare_id: str
    generated_at: str
    rows: list[CompareRow] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkPackConfig:
    pack_id: str
    presets: list[str]
    trials: int
    base_run_config: BenchmarkConfig
    out_dir: str

    def validate(self) -> None:
        if not self.presets:
            raise ValueError("--presets must include at least one preset")
        if self.trials <= 0:
            raise ValueError("--trials must be > 0")


@dataclass
class BenchmarkPackRun:
    preset: str
    trial: int
    compare_id: str
    compare_dir: str


@dataclass
class BenchmarkPackRow:
    pack_id: str
    preset: str
    backend: str
    embedding_mode: str
    workload: str
    rate: float
    docs_total: int
    trials: int
    median_success_rate: float | None
    median_freshness_p50_ms: float | None
    median_freshness_p95_ms: float | None
    median_embedding_p50_ms: float | None
    median_write_ack_p50_ms: float | None
    median_visibility_p50_ms: float | None
    median_actual_submission_rate: float | None
    median_actual_completion_rate: float | None
    trial_compare_ids: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["trial_compare_ids"] = ",".join(self.trial_compare_ids)
        return record


@dataclass
class BenchmarkPackSummary:
    pack_id: str
    generated_at: str
    rows: list[BenchmarkPackRow] = field(default_factory=list)
    trial_runs: list[BenchmarkPackRun] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
