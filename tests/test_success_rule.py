from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.models import DocLifecycle
from freshness_benchmark.qdrant_backend import match_doc_in_hits


class SuccessRuleTest(unittest.TestCase):
    def test_top_k_hit_any_position_is_success(self) -> None:
        hits = [
            {"payload": {"doc_id": "doc-0003"}},
            {"payload": {"doc_id": "doc-0008"}},
            {"payload": {"doc_id": "doc-0010"}},
            {"payload": {"doc_id": "doc-0005"}},
        ]
        self.assertTrue(match_doc_in_hits(hits, "doc-0010"))
        self.assertFalse(match_doc_in_hits(hits, "doc-0999"))

    def test_timeout_marks_failure_and_reason(self) -> None:
        lifecycle = DocLifecycle(run_id="r1", doc_id="doc-0001", text="x")
        lifecycle.mark_timeout("Doc not found in top-10 within 120s")

        self.assertEqual(lifecycle.status, "timeout")
        self.assertEqual(lifecycle.error, "Doc not found in top-10 within 120s")
        self.assertIsNone(lifecycle.freshness_ms)


if __name__ == "__main__":
    unittest.main()
