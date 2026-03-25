from __future__ import annotations

from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.qdrant_backend import QdrantBackend


class QdrantBackendTest(unittest.TestCase):
    def test_prepare_run_ignores_already_exists_conflict(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark", "run-1")

        with patch.object(
            QdrantBackend,
            "_request_with_status",
            return_value=(409, {"status": {"error": "Collection already exists"}}),
        ), patch.object(
            QdrantBackend,
            "_collection_vector_size",
            return_value=1536,
        ), patch.object(QdrantBackend, "reset_run_data") as reset_mock:
            backend.prepare_run(vector_size=1536)

        reset_mock.assert_called_once()

    def test_prepare_run_recreates_collection_when_vector_size_changes(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark", "run-1")
        with patch.object(
            QdrantBackend,
            "_request_with_status",
            return_value=(409, {"status": {"error": "Collection already exists"}}),
        ), patch.object(
            QdrantBackend,
            "_collection_vector_size",
            return_value=1536,
        ), patch.object(QdrantBackend, "_delete_collection") as delete_mock, patch.object(
            QdrantBackend,
            "_create_collection",
        ) as create_mock, patch.object(QdrantBackend, "reset_run_data"):
            backend.prepare_run(vector_size=128)

        delete_mock.assert_called_once()
        create_mock.assert_called_once_with(128)

    def test_prepare_run_raises_for_other_conflicts(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark", "run-1")
        with patch.object(
            QdrantBackend,
            "_request_with_status",
            return_value=(409, {"status": {"error": "some other conflict"}}),
        ):
            with self.assertRaises(RuntimeError):
                backend.prepare_run(vector_size=1536)

    def test_reset_run_data_filters_by_run_id(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark", "run-1")
        with patch.object(QdrantBackend, "_request", return_value={}) as request_mock:
            backend.reset_run_data()

        _, kwargs = request_mock.call_args
        self.assertEqual(kwargs["query"], {"wait": "true"})
        self.assertEqual(
            kwargs["body"]["filter"]["must"][0]["match"]["value"],
            "run-1",
        )

    def test_normalize_point_id_returns_uuid(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark", "run-1")
        point_id = backend._normalize_point_id("doc-000001")
        self.assertNotEqual(point_id, "doc-000001")
        self.assertEqual(str(uuid.UUID(point_id)), point_id)


if __name__ == "__main__":
    unittest.main()
