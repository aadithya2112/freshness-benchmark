from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freshness_benchmark.visualize import (  # noqa: E402
    _cdf_points,
    _find_latest_run_dir,
    _histogram,
    generate_html_report,
)


class VisualizeTest(unittest.TestCase):
    def test_histogram_counts_cover_all_values(self) -> None:
        values = [10.0, 11.0, 12.0, 13.0, 20.0]
        counts, min_v, max_v = _histogram(values, bins=5)
        self.assertEqual(sum(counts), len(values))
        self.assertEqual(min_v, 10.0)
        self.assertEqual(max_v, 20.0)

    def test_cdf_monotonic(self) -> None:
        points = _cdf_points([5.0, 1.0, 3.0, 2.0])
        self.assertEqual(points[0][0], 1.0)
        self.assertEqual(points[-1][0], 5.0)
        self.assertGreater(points[-1][1], points[0][1])

    def test_find_latest_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            run_a = base / "run-a"
            run_b = base / "run-b"
            run_a.mkdir()
            run_b.mkdir()
            (run_a / "summary.json").write_text("{}", encoding="utf-8")
            (run_a / "metrics.csv").write_text("run_id\nx\n", encoding="utf-8")
            (run_b / "summary.json").write_text("{}", encoding="utf-8")
            (run_b / "metrics.csv").write_text("run_id\ny\n", encoding="utf-8")
            # Touch run_b after run_a so mtime is newest.
            (run_b / "summary.json").write_text("{}", encoding="utf-8")
            latest = _find_latest_run_dir(base)
            self.assertEqual(latest.name, "run-b")

    def test_generate_html_report_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run-x"
            run_dir.mkdir()
            (run_dir / "summary.json").write_text(
                """{
  "run_id": "r1",
  "docs_total": 2,
  "docs_success": 2,
  "docs_timeout": 0,
  "docs_error": 0,
  "success_rate": 1.0,
  "freshness_ms": {"min": 100, "p50": 120, "p95": 140, "p99": 145, "max": 150},
  "embedding_ms": {"min": 80, "p50": 90, "p95": 110, "p99": 115, "max": 120},
  "index_ack_ms": {"min": 5, "p50": 6, "p95": 7, "p99": 8, "max": 9},
  "config": {}
}""",
                encoding="utf-8",
            )
            (run_dir / "metrics.csv").write_text(
                "run_id,doc_id,status,error,t_ingested,t_embedding_done,t_index_update_done,t_first_search_success,embedding_ms,index_ack_ms,freshness_ms\n"
                "r1,doc-1,success,,,,,,90,6,120\n"
                "r1,doc-2,success,,,,,,100,7,140\n",
                encoding="utf-8",
            )
            output = generate_html_report(run_dir)
            content = output.read_text(encoding="utf-8")
            self.assertTrue(output.exists())
            self.assertIn("Freshness Latency Report", content)
            self.assertIn("Run <strong>r1</strong>", content)


if __name__ == "__main__":
    unittest.main()
