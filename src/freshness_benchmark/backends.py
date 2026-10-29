from __future__ import annotations

from typing import Protocol

from .models import BenchmarkConfig
from .pgvector_backend import PgvectorBackend
from .qdrant_backend import QdrantBackend
from .weaviate_backend import WeaviateBackend


class VectorBackend(Protocol):
    name: str

    def prepare_run(self, vector_size: int) -> None:
        ...

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, object]) -> None:
        ...

    def search(self, vector: list[float], limit: int) -> list[dict[str, object]]:
        ...

    def reset_run_data(self) -> None:
        ...

    def backend_info(self) -> dict[str, object]:
        ...

    def close(self) -> None:
        ...


def build_backend(config: BenchmarkConfig) -> VectorBackend:
    if config.backend == "qdrant":
        return QdrantBackend(
            qdrant_url=config.qdrant_url,
            collection=config.collection,
            run_id=config.run_id,
            search_scope=config.search_scope,
        )
    if config.backend == "weaviate":
        return WeaviateBackend(
            weaviate_url=config.weaviate_url,
            collection=config.collection,
            run_id=config.run_id,
            search_scope=config.search_scope,
        )
    if config.backend == "pgvector":
        return PgvectorBackend(
            dsn=config.pgvector_dsn or "",
            collection=config.collection,
            run_id=config.run_id,
            search_scope=config.search_scope,
        )
    raise ValueError(f"Unsupported backend: {config.backend}")
