from concurrent.futures import wait
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from freshness_benchmark.embeddings import CachedEmbeddingSource
from freshness_benchmark.models import DocLifecycle
from freshness_benchmark.probing import VisibilityScheduler
from test_runner import _config


class ProbeTest(unittest.TestCase):
    def record(self, doc_id):
        now = time.monotonic()
        return DocLifecycle('test','qdrant','precomputed','synthetic-small',doc_id,1,'text',
                            monotonic_submitted=now, monotonic_write_acked=now)

    def test_sleeping_document_does_not_block_later_document(self):
        class Backend:
            def search(self, vector, limit):
                return [] if vector == [0] else [{'payload': {'doc_id': 'fast'}}]
        cfg = replace(_config('/tmp'), search_concurrency=1, poll_interval_ms=100, max_wait_s=0.2)
        scheduler = VisibilityScheduler(Backend(), cfg)
        slow, fast = self.record('slow'), self.record('fast')
        first = scheduler.submit(slow, [0])
        second = scheduler.submit(fast, [1])
        self.assertEqual(second.result(timeout=1).status, 'success')
        self.assertLess(fast.freshness_ms, 90)
        self.assertEqual(first.result(timeout=1).status, 'timeout')
        scheduler.close()

    def test_response_after_deadline_is_not_success(self):
        class Backend:
            def search(self, vector, limit):
                time.sleep(0.05)
                return [{'payload': {'doc_id': 'late'}}]
        cfg = replace(_config('/tmp'), max_wait_s=0.02)
        scheduler = VisibilityScheduler(Backend(), cfg)
        result = scheduler.submit(self.record('late'), [1]).result(timeout=1)
        scheduler.close()
        self.assertEqual(result.status, 'timeout')
        self.assertIsNone(result.freshness_ms)
        self.assertTrue(result.probes[0]['found'])

    def test_cache_rejects_text_drift_and_nonfinite_vectors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'cache.json'
            body = {'metadata': {'dimensions': 2}, 'vectors': {'id': [1,0]},
                    'text_sha256': {'id': hashlib.sha256(b'text').hexdigest()}}
            path.write_text(json.dumps(body))
            source = CachedEmbeddingSource(str(path))
            self.assertEqual(source.get_vector('id','text'), [1,0])
            with self.assertRaises(ValueError):
                source.get_vector('id','changed')
            body['vectors']['id'] = [float('nan'),0]
            path.write_text(json.dumps(body))
            with self.assertRaises(ValueError):
                CachedEmbeddingSource(str(path))
