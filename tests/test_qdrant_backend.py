from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.qdrant_backend import QdrantBackend


class QdrantBackendTest(unittest.TestCase):
    def test_ensure_collection_ignores_already_exists_conflict(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark")

        with patch.object(
            QdrantBackend,
            "_request_with_status",
            return_value=(409, {"status": {"error": "Collection already exists"}}),
        ):
            backend.ensure_collection(vector_size=1536)

    def test_ensure_collection_raises_for_other_conflicts(self) -> None:
        backend = QdrantBackend("http://localhost:6333", "freshness_benchmark")
        with patch.object(
            QdrantBackend,
            "_request_with_status",
            return_value=(409, {"status": {"error": "some other conflict"}}),
        ):
            with self.assertRaises(RuntimeError):
                backend.ensure_collection(vector_size=1536)


if __name__ == "__main__":
    unittest.main()
