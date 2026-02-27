from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from .embeddings import EmbeddingClient
from .models import BenchmarkConfig, DocLifecycle, now_utc
from .qdrant_backend import QdrantBackend, match_doc_in_hits
from .reporting import (
    print_summary,
    summarize,
    write_metrics_csv,
    write_summary_json,
    write_trace_jsonl,
)


def synthetic_doc(doc_num: int) -> tuple[str, str]:
    doc_id = f"doc-{doc_num:04d}"
    anchor = f"freshness-anchor-{doc_id}"
    text = (
        f"This is synthetic benchmark document {doc_id}. "
        f"Unique retrieval anchor phrase: {anchor}. "
        f"Sequence={doc_num}."
    )
    return doc_id, text


def _await_searchable(
    backend: QdrantBackend,
    vector: list[float],
    doc_id: str,
    top_k: int,
    poll_interval_ms: int,
    max_wait_s: int,
) -> bool:
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        hits = backend.search(vector=vector, limit=top_k)
        if match_doc_in_hits(hits, doc_id):
            return True
        time.sleep(poll_interval_ms / 1000.0)
    return False


def run_benchmark(config: BenchmarkConfig) -> None:
    output_dir = Path(config.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    embed_client = EmbeddingClient(
        provider=config.provider,
        base_url=config.base_url,
        model=config.embedding_model,
    )
    backend = QdrantBackend(config.qdrant_url, config.collection)

    collection_ready = False
    records: list[DocLifecycle] = []

    start_monotonic = time.monotonic()
    interval = 1.0 / config.rate

    try:
        for idx in range(1, config.docs + 1):
            scheduled = start_monotonic + ((idx - 1) * interval)
            sleep_for = scheduled - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)

            doc_id, text = synthetic_doc(idx)
            lifecycle = DocLifecycle(run_id=config.run_id, doc_id=doc_id, text=text)
            lifecycle.t_ingested = now_utc()

            try:
                vector = embed_client.embed(text)
                lifecycle.t_embedding_done = now_utc()

                if not collection_ready:
                    backend.ensure_collection(vector_size=len(vector))
                    collection_ready = True

                backend.upsert(
                    point_id=idx,
                    vector=vector,
                    payload={
                        "run_id": config.run_id,
                        "doc_id": doc_id,
                        "text": text,
                    },
                )
                lifecycle.t_index_update_done = now_utc()

                found = _await_searchable(
                    backend=backend,
                    vector=vector,
                    doc_id=doc_id,
                    top_k=config.top_k,
                    poll_interval_ms=config.poll_interval_ms,
                    max_wait_s=config.max_wait_s,
                )
                if found:
                    lifecycle.t_first_search_success = now_utc()
                    lifecycle.mark_success()
                else:
                    lifecycle.mark_timeout(
                        f"Doc not found in top-{config.top_k} within {config.max_wait_s}s"
                    )
            except Exception as exc:  # pragma: no cover - integration path
                lifecycle.mark_error(str(exc))

            records.append(lifecycle)
    finally:
        embed_client.close()
        backend.close()

    summary = summarize(config.run_id, records, config=asdict(config))
    write_trace_jsonl(output_dir / "trace.jsonl", records)
    write_metrics_csv(output_dir / "metrics.csv", records)
    write_summary_json(output_dir / "summary.json", summary)
    print_summary(summary)
