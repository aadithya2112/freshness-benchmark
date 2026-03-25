from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.models import DocLifecycle
from freshness_benchmark.reporting import metric_stats, percentile


class MetricsTest(unittest.TestCase):
    def test_freshness_computed_from_stage_timestamps(self) -> None:
        base = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)
        lifecycle = DocLifecycle(
            run_id="r1",
            backend="qdrant",
            embedding_mode="precomputed",
            workload="synthetic-small",
            doc_id="doc-0001",
            doc_num=1,
            text="x",
        )
        lifecycle.t_submitted = base
        lifecycle.t_embedding_done = base + timedelta(milliseconds=120)
        lifecycle.t_write_acked = base + timedelta(milliseconds=200)
        lifecycle.t_searchable = base + timedelta(milliseconds=650)
        lifecycle.mark_success()

        self.assertEqual(lifecycle.status, "success")
        self.assertAlmostEqual(lifecycle.freshness_ms or 0.0, 650.0, places=6)
        self.assertAlmostEqual(lifecycle.embedding_ms or 0.0, 120.0, places=6)
        self.assertAlmostEqual(lifecycle.write_ack_ms or 0.0, 80.0, places=6)
        self.assertAlmostEqual(lifecycle.visibility_ms or 0.0, 450.0, places=6)

    def test_missing_searchable_timestamp_has_no_freshness(self) -> None:
        base = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)
        lifecycle = DocLifecycle(
            run_id="r1",
            backend="qdrant",
            embedding_mode="precomputed",
            workload="synthetic-small",
            doc_id="doc-0002",
            doc_num=2,
            text="x",
        )
        lifecycle.t_submitted = base
        lifecycle.t_embedding_done = base + timedelta(milliseconds=90)
        lifecycle.t_write_acked = base + timedelta(milliseconds=150)
        lifecycle.mark_timeout("timeout")

        self.assertEqual(lifecycle.status, "timeout")
        self.assertIsNone(lifecycle.freshness_ms)
        self.assertIsNone(lifecycle.visibility_ms)
        self.assertEqual(lifecycle.error, "timeout")

    def test_percentiles_handle_small_and_empty_sets(self) -> None:
        self.assertIsNone(percentile([], 95))
        self.assertEqual(percentile([10.0], 95), 10.0)
        self.assertEqual(percentile([1.0, 3.0, 5.0], 0), 1.0)
        self.assertEqual(percentile([1.0, 3.0, 5.0], 100), 5.0)

        stats = metric_stats([])
        self.assertIsNone(stats["p95"])


if __name__ == "__main__":
    unittest.main()
