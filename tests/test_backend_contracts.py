from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.pgvector_backend import PgvectorBackend
from freshness_benchmark.qdrant_backend import QdrantBackend
from freshness_benchmark.weaviate_backend import WeaviateBackend


class _BackendContractMixin:
    def assert_backend_contract(self, backend: object) -> None:
        for attr in (
            "prepare_run",
            "upsert",
            "search",
            "reset_run_data",
            "backend_info",
            "close",
        ):
            self.assertTrue(callable(getattr(backend, attr)))


class BackendContractTest(_BackendContractMixin, unittest.TestCase):
    def test_qdrant_backend_implements_contract(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark", "run-1")
        self.assert_backend_contract(backend)

    def test_weaviate_backend_implements_contract(self) -> None:
        backend = WeaviateBackend("http://localhost:8080", "freshness_benchmark", "run-1")
        self.assert_backend_contract(backend)

    def test_pgvector_backend_implements_contract(self) -> None:
        backend = PgvectorBackend("postgresql://localhost/freshness", "freshness_benchmark", "run-1")
        self.assert_backend_contract(backend)

    def test_weaviate_search_builds_graphql_not_embedded_json(self) -> None:
        backend = WeaviateBackend("http://localhost:8080", "freshness_benchmark", "run-1")
        query = backend._build_search_query([0.1, 0.2], limit=5)
        self.assertIn('nearVector: {vector: [0.1, 0.2]}', query)
        self.assertIn('where: {path: ["run_id"], operator: Equal, valueText: "run-1"}', query)

    def test_weaviate_search_normalizes_payloads(self) -> None:
        backend = WeaviateBackend("http://localhost:8080", "freshness_benchmark", "run-1")
        with patch.object(
            WeaviateBackend,
            "_request",
            return_value=(
                200,
                {
                    "data": {
                        "Get": {
                            backend.class_name: [
                                {"doc_id": "doc-1", "run_id": "run-1", "text": "hello"}
                            ]
                        }
                    }
                },
            ),
        ):
            hits = backend.search([0.1, 0.2], limit=5)
        self.assertEqual(hits[0]["payload"]["doc_id"], "doc-1")


class _Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self._rows = [({"doc_id": "doc-1", "run_id": "run-1"},)]

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[object]]:
        return self._rows

    def fetchone(self) -> tuple[object]:
        return ("version",)

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class PgvectorBackendTest(unittest.TestCase):
    def test_pgvector_search_normalizes_payloads(self) -> None:
        backend = PgvectorBackend("postgresql://localhost/freshness", "freshness_benchmark", "run-1")
        conn = _Connection()
        with patch.object(PgvectorBackend, "_connection", return_value=conn):
            hits = backend.search([0.1, 0.2], limit=3)
        self.assertEqual(hits[0]["payload"]["doc_id"], "doc-1")


if __name__ == "__main__":
    unittest.main()
