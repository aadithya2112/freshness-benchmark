from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.models import BenchmarkConfig
from freshness_benchmark.workload import generate_workload_doc, load_workload_docs


def _base_config() -> BenchmarkConfig:
    return BenchmarkConfig(
        run_id="run-1",
        docs=10,
        rate=1.0,
        collection="freshness_benchmark",
        backend="qdrant",
        qdrant_url="http://localhost:6333",
        weaviate_url="http://localhost:8080",
        pgvector_dsn="postgresql://localhost/freshness",
        embedding_mode="precomputed",
        embedding_model="unused",
        provider="openrouter",
        base_url="https://example.invalid",
        embedding_dimensions=8,
        top_k=10,
        poll_interval_ms=100,
        max_wait_s=10,
        embedding_concurrency=1,
        write_concurrency=1,
        search_concurrency=1,
        workload="synthetic-small",
        dataset_path=None,
        dataset_format=None,
        text_field=None,
        id_field=None,
        out_dir="artifacts/test",
    )


class WorkloadTest(unittest.TestCase):
    def test_synthetic_doc_is_deterministic(self) -> None:
        doc = generate_workload_doc(1, "synthetic-small")
        self.assertEqual(doc.doc_id, "doc-000001")
        self.assertIn("freshness-anchor-doc-000001", doc.text)
        self.assertEqual(doc.text, doc.source_text)

    def test_load_jsonl_dataset_with_explicit_fields(self) -> None:
        config = _base_config()
        config.workload = "dataset"
        config.docs = 2
        config.dataset_path = str(Path(__file__).resolve().parent / "fixtures" / "sample.jsonl")
        config.dataset_format = "jsonl"
        config.text_field = "body"
        config.id_field = "slug"
        config.validate()

        docs = load_workload_docs(config)
        self.assertEqual([doc.doc_id for doc in docs], ["intro-post", "release-notes"])
        self.assertIn("Freshness benchmark retrieval anchor", docs[0].text)
        self.assertEqual(docs[0].source_text, "Intro post about freshness benchmarking.")

    def test_load_jsonl_dataset_defaults_id_to_row_number(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dataset = Path(td) / "rows.jsonl"
            dataset.write_text('{"text":"First"}\n{"text":"Second"}\n', encoding="utf-8")

            config = _base_config()
            config.workload = "dataset"
            config.docs = 2
            config.dataset_path = str(dataset)
            config.dataset_format = "jsonl"
            config.text_field = "text"
            config.id_field = None
            config.validate()

            docs = load_workload_docs(config)
            self.assertEqual([doc.doc_id for doc in docs], ["row-000001", "row-000002"])

    def test_load_text_dir_dataset(self) -> None:
        config = _base_config()
        config.workload = "dataset"
        config.docs = 2
        config.dataset_path = str(Path(__file__).resolve().parent / "fixtures" / "text_corpus")
        config.dataset_format = "text-dir"
        config.text_field = None
        config.id_field = None
        config.validate()

        docs = load_workload_docs(config)
        self.assertEqual([doc.doc_id for doc in docs], ["guides/intro.md", "notes/tips.txt"])
        self.assertEqual(docs[0].source_ref, "guides/intro.md")
        self.assertIn("freshness-anchor-guides/intro.md", docs[0].text)


if __name__ == "__main__":
    unittest.main()
