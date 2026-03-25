from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.benchmark_pack import (  # noqa: E402
    available_benchmark_pack_presets,
    run_benchmark_pack,
)
from freshness_benchmark.models import BenchmarkConfig, BenchmarkPackConfig  # noqa: E402


class FakeEmbeddingSource:
    def __init__(self, *, dimensions: int = 4) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def metadata(self) -> dict[str, object]:
        return {"type": "fake", "dimensions": self._dimensions}

    def get_vector(self, doc_id: str, text: str) -> list[float]:
        del text
        digest = hashlib.sha256(doc_id.encode("utf-8")).digest()
        sequence = float(int.from_bytes(digest[:2], "big"))
        return [sequence, sequence / 10.0, 0.0, 1.0]

    def close(self) -> None:
        return None


class FakeBackend:
    name = "fake"

    def __init__(self, backend_name: str, run_id: str, visible_after_s: float = 0.005) -> None:
        self.backend_name = backend_name
        self.run_id = run_id
        self.visible_after_s = visible_after_s
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, object]] = {}

    def prepare_run(self, vector_size: int) -> None:
        self.reset_run_data()
        self.vector_size = vector_size

    def reset_run_data(self) -> None:
        with self._lock:
            self._entries = {}

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, object]) -> None:
        with self._lock:
            self._entries[point_id] = {
                "vector": list(vector),
                "payload": dict(payload),
                "visible_at": time.monotonic() + self.visible_after_s,
            }

    def search(self, vector: list[float], limit: int) -> list[dict[str, object]]:
        now = time.monotonic()
        with self._lock:
            visible = [
                entry
                for entry in self._entries.values()
                if entry["visible_at"] <= now
            ]
        visible.sort(key=lambda entry: abs(entry["vector"][0] - vector[0]))
        return [{"payload": entry["payload"]} for entry in visible[:limit]]

    def backend_info(self) -> dict[str, object]:
        return {"name": self.backend_name, "version": "test"}

    def close(self) -> None:
        return None


def _base_run(tmpdir: str) -> BenchmarkConfig:
    return BenchmarkConfig(
        run_id="pack-seed",
        docs=1,
        rate=1.0,
        collection="freshness_benchmark",
        backend="qdrant",
        qdrant_url="http://localhost:6333",
        weaviate_url="http://localhost:8080",
        pgvector_dsn="postgresql://localhost/freshness",
        embedding_mode="precomputed",
        embedding_model="text-embedding-3-small",
        provider="openrouter",
        base_url="https://example.invalid",
        embedding_dimensions=4,
        top_k=10,
        poll_interval_ms=5,
        max_wait_s=1,
        embedding_concurrency=2,
        write_concurrency=2,
        search_concurrency=2,
        workload="synthetic-medium",
        dataset_path=None,
        dataset_format=None,
        text_field=None,
        id_field=None,
        out_dir=tmpdir,
    )


class BenchmarkPackTest(unittest.TestCase):
    def test_available_presets_include_expected_names(self) -> None:
        presets = available_benchmark_pack_presets()
        self.assertIn("baseline_docs_precomputed", presets)
        self.assertIn("baseline_synthetic_precomputed", presets)
        self.assertIn("embedding_reality_check", presets)

    def test_run_benchmark_pack_writes_aggregated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = BenchmarkPackConfig(
                pack_id="pack-1",
                presets=["baseline_synthetic_precomputed"],
                trials=2,
                base_run_config=_base_run(str(Path(td) / "seed")),
                out_dir=td,
            )
            config.validate()
            test_presets = {
                "baseline_synthetic_precomputed": {
                    "description": "Synthetic control",
                    "docs": 2,
                    "backends": ["qdrant", "weaviate"],
                    "rates": [4.0],
                    "embedding_modes": ["precomputed"],
                    "workload": "synthetic-medium",
                    "dataset_path": None,
                    "dataset_format": None,
                    "text_field": None,
                    "id_field": None,
                    "embedding_model": "text-embedding-3-small",
                }
            }
            with patch(
                "freshness_benchmark.benchmark_pack.available_benchmark_pack_presets",
                return_value=test_presets,
            ):
                summary = run_benchmark_pack(
                    config,
                    backend_factory=lambda cfg: FakeBackend(cfg.backend, cfg.run_id),
                    embedding_source_factory=lambda cfg: FakeEmbeddingSource(
                        dimensions=cfg.embedding_dimensions
                    ),
                )

            self.assertEqual(len(summary.rows), 2)
            self.assertTrue((Path(td) / "benchmark_pack.json").exists())
            self.assertTrue((Path(td) / "benchmark_pack.csv").exists())
            self.assertTrue((Path(td) / "benchmark_pack.html").exists())
            html = (Path(td) / "benchmark_pack.html").read_text(encoding="utf-8")
            self.assertIn("Benchmark Pack", html)
            self.assertIn("Synthetic control", html)


if __name__ == "__main__":
    unittest.main()
