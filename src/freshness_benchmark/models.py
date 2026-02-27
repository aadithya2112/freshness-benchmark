from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
    qdrant_url: str
    embedding_model: str
    provider: str
    base_url: str
    top_k: int
    poll_interval_ms: int
    max_wait_s: int
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
        if not self.collection:
            raise ValueError("--collection must not be empty")
        if not self.embedding_model:
            raise ValueError("--embedding-model must not be empty")


@dataclass
class DocLifecycle:
    run_id: str
    doc_id: str
    text: str
    t_ingested: datetime | None = None
    t_embedding_done: datetime | None = None
    t_index_update_done: datetime | None = None
    t_first_search_success: datetime | None = None
    freshness_ms: float | None = None
    embedding_ms: float | None = None
    index_ack_ms: float | None = None
    status: str = "pending"
    error: str | None = None

    def finalize_metrics(self) -> None:
        self.embedding_ms = delta_ms(self.t_ingested, self.t_embedding_done)
        self.index_ack_ms = delta_ms(self.t_embedding_done, self.t_index_update_done)
        self.freshness_ms = delta_ms(self.t_ingested, self.t_first_search_success)

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
        record["t_ingested"] = to_iso(self.t_ingested)
        record["t_embedding_done"] = to_iso(self.t_embedding_done)
        record["t_index_update_done"] = to_iso(self.t_index_update_done)
        record["t_first_search_success"] = to_iso(self.t_first_search_success)
        return record


@dataclass
class RunSummary:
    run_id: str
    docs_total: int
    docs_success: int
    docs_timeout: int
    docs_error: int
    success_rate: float
    freshness_ms: dict[str, float | None]
    embedding_ms: dict[str, float | None]
    index_ack_ms: dict[str, float | None]
    config: dict[str, Any]
