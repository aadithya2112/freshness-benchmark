"""Fair visibility probing: a worker performs one request, never sleeps per document."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading
import time

from .models import now_utc
from .qdrant_backend import match_doc_in_hits


class VisibilityScheduler:
    def __init__(self, backend, config):
        self.backend, self.config = backend, config
        self.condition = threading.Condition()
        self.pending = []
        self.active = {}
        self.closing = False
        self.pool = ThreadPoolExecutor(max_workers=config.search_concurrency)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def submit(self, lifecycle, vector):
        future = Future()
        with self.condition:
            self.pending.append((time.monotonic(), lifecycle, vector, future))
            self.condition.notify()
        return future

    def _probe(self, lifecycle, vector):
        start = time.monotonic()
        hits = self.backend.search(vector=vector, limit=self.config.top_k)
        return start, time.monotonic(), match_doc_in_hits(hits, lifecycle.doc_id)

    def _loop(self):
        while True:
            with self.condition:
                now = time.monotonic()
                for task, item in list(self.active.items()):
                    if not task.done():
                        continue
                    del self.active[task]
                    due, record, vector, future = item
                    try:
                        start, end, found = task.result()
                        elapsed = (end - record.monotonic_submitted) * 1000
                        record.search_attempts += 1
                        record.probes.append({"start_ms": (start-record.monotonic_submitted)*1000,
                                              "end_ms": elapsed, "found": found})
                        if found and end <= record.monotonic_submitted + self.config.max_wait_s:
                            record.monotonic_searchable = end
                            record.t_searchable = now_utc()
                            record.mark_success()
                            future.set_result(record)
                        elif end >= record.monotonic_submitted + self.config.max_wait_s:
                            record.mark_timeout("Submission-to-observation deadline exceeded")
                            future.set_result(record)
                        else:
                            # A negative ANN result does not prove absence: lower bound stays zero.
                            self.pending.append((end+self.config.poll_interval_ms/1000, record, vector, future))
                    except Exception as exc:
                        record.mark_error(str(exc))
                        future.set_result(record)
                self.pending.sort(key=lambda item: item[0])
                while self.pending and len(self.active) < self.config.search_concurrency:
                    due, record, vector, future = self.pending[0]
                    if due > now:
                        break
                    self.pending.pop(0)
                    if now >= record.monotonic_submitted + self.config.max_wait_s:
                        record.mark_timeout("Deadline exceeded before probe dispatch")
                        future.set_result(record)
                        continue
                    if record.search_queue_ms is None:
                        record.search_queue_ms = (now-record.monotonic_write_acked)*1000
                    task = self.pool.submit(self._probe, record, vector)
                    self.active[task] = (due, record, vector, future)
                    task.add_done_callback(lambda _: self._wake())
                if self.closing and not self.pending and not self.active:
                    return
                self.condition.wait(timeout=0.001 if self.pending else 0.01)

    def _wake(self):
        with self.condition:
            self.condition.notify()

    def close(self):
        with self.condition:
            self.closing = True
            self.condition.notify()
        self.thread.join()
        self.pool.shutdown()
