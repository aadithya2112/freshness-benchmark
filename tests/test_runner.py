from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.models import BenchmarkConfig, CompareConfig
from freshness_benchmark.runner import run_benchmark, run_compare


class FakeEmbeddingSource:
    def __init__(self, *, fail_doc_id: str | None = None, dimensions: int = 4) -> None:
        self.fail_doc_id = fail_doc_id
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def metadata(self) -> dict[str, object]:
        return {"type": "fake", "dimensions": self._dimensions}

    def get_vector(self, doc_id: str, text: str) -> list[float]:
        del text
        if self.fail_doc_id == doc_id:
            raise RuntimeError(f"embedding failed for {doc_id}")
        digest = hashlib.sha256(doc_id.encode("utf-8")).digest()
        sequence = float(int.from_bytes(digest[:2], "big"))
        return [sequence, sequence / 10.0, 0.0, 1.0]

    def close(self) -> None:
        return None


class FakeBackend:
    name = "fake"

    def __init__(self, backend_name: str, run_id: str, visible_after_s: float = 0.15) -> None:
        self.backend_name = backend_name
        self.run_id = run_id
        self.visible_after_s = visible_after_s
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, object]] = {}
        self._prepared = False

    def prepare_run(self, vector_size: int) -> None:
        self._prepared = True
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


def _config(tmpdir: str, *, run_id: str = "run-1") -> BenchmarkConfig:
    return BenchmarkConfig(
        run_id=run_id,
        docs=3,
        rate=20.0,
        collection="freshness_benchmark",
        backend="qdrant",
        qdrant_url="http://localhost:6333",
        weaviate_url="http://localhost:8080",
        pgvector_dsn="postgresql://localhost/freshness",
        embedding_mode="precomputed",
        embedding_model="unused",
        provider="openrouter",
        base_url="https://example.invalid",
        embedding_dimensions=4,
        top_k=10,
        poll_interval_ms=20,
        max_wait_s=2,
        embedding_concurrency=2,
        write_concurrency=2,
        search_concurrency=2,
        workload="synthetic-small",
        dataset_path=None,
        dataset_format=None,
        text_field=None,
        id_field=None,
        out_dir=tmpdir,
    )


class RunnerTest(unittest.TestCase):
    def test_pipeline_submits_later_docs_before_earlier_doc_is_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = _config(td)
            summary = run_benchmark(
                config,
                backend_factory=lambda cfg: FakeBackend(cfg.backend, cfg.run_id, visible_after_s=0.18),
                embedding_source_factory=lambda cfg: FakeEmbeddingSource(dimensions=cfg.embedding_dimensions),
            )
            self.assertEqual(summary.docs_success, 3)

            trace_path = Path(td) / "trace.jsonl"
            records = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            first_searchable = datetime.fromisoformat(records[0]["t_searchable"])
            third_submitted = datetime.fromisoformat(records[2]["t_submitted"])
            self.assertLess(third_submitted, first_searchable)
            self.assertGreater(summary.actual_submission_rate, 10.0)

    def test_compare_writes_combined_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base_run = _config(str(Path(td) / "runs" / "seed"))
            compare_config = CompareConfig(
                compare_id="cmp-1",
                backends=["qdrant", "weaviate"],
                rates=[2.0, 4.0],
                embedding_modes=["precomputed"],
                base_run_config=base_run,
                out_dir=td,
            )
            summary = run_compare(
                compare_config,
                backend_factory=lambda cfg: FakeBackend(cfg.backend, cfg.run_id, visible_after_s=0.01),
                embedding_source_factory=lambda cfg: FakeEmbeddingSource(dimensions=cfg.embedding_dimensions),
            )
            self.assertEqual(len(summary.rows), 4)
            self.assertTrue((Path(td) / "comparison.json").exists())
            self.assertTrue((Path(td) / "comparison.csv").exists())
            self.assertTrue((Path(td) / "comparison.html").exists())

    def test_partial_failures_are_accounted_for(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = _config(td, run_id="run-errors")
            config.docs = 2
            summary = run_benchmark(
                config,
                backend_factory=lambda cfg: FakeBackend(cfg.backend, cfg.run_id, visible_after_s=0.01),
                embedding_source_factory=lambda cfg: FakeEmbeddingSource(
                    dimensions=cfg.embedding_dimensions,
                    fail_doc_id="doc-000002",
                ),
            )
            self.assertEqual(summary.docs_success, 1)
            self.assertEqual(summary.docs_error, 1)

    def test_dataset_workload_runs_and_records_dataset_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = _config(td, run_id="run-dataset")
            config.workload = "dataset"
            config.docs = 2
            config.dataset_path = str(Path(__file__).resolve().parent / "fixtures" / "sample.jsonl")
            config.dataset_format = "jsonl"
            config.text_field = "body"
            config.id_field = "slug"
            config.validate()

            summary = run_benchmark(
                config,
                backend_factory=lambda cfg: FakeBackend(cfg.backend, cfg.run_id, visible_after_s=0.01),
                embedding_source_factory=lambda cfg: FakeEmbeddingSource(dimensions=cfg.embedding_dimensions),
            )

            self.assertEqual(summary.docs_success, 2)
            self.assertEqual(summary.dataset["format"], "jsonl")
            trace = (Path(td) / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("Intro post about freshness benchmarking.", trace)
            self.assertIn("freshness-anchor-intro-post", trace)


if __name__ == "__main__":
    unittest.main()
