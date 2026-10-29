from __future__ import annotations

import hashlib
import subprocess
import platform
import socket
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

from .backends import VectorBackend, build_backend
from .embeddings import CachedEmbeddingSource, EmbeddingSource, build_embedding_source
from .probing import VisibilityScheduler
from .models import BenchmarkConfig, CompareConfig, CompareSummary, DocLifecycle, RunSummary, now_utc
from .qdrant_backend import match_doc_in_hits
from .reporting import (
    compare_row_from_summary,
    print_summary,
    summarize,
    write_compare_csv,
    write_compare_summary_json,
    write_metrics_csv,
    write_summary_json,
    write_trace_jsonl,
    metric_stats,
)
from .visualize import generate_comparison_html_report, generate_html_report
from .workload import load_workload_docs


BackendFactory = Callable[[BenchmarkConfig], VectorBackend]
EmbeddingSourceFactory = Callable[[BenchmarkConfig], EmbeddingSource]


class _BackendPreparation:
    def __init__(self, backend: VectorBackend) -> None:
        self._backend = backend
        self._lock = threading.Lock()
        self._prepared = False

    def ensure(self, vector_size: int) -> None:
        with self._lock:
            if self._prepared:
                return
            self._backend.prepare_run(vector_size)
            self._prepared = True


def _docker_images_from_compose(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    images: dict[str, str] = {}
    current_service: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("  ") and line.strip().endswith(":") and not line.startswith("    "):
            current_service = line.strip().rstrip(":")
            continue
        if current_service and line.strip().startswith("image:"):
            images[current_service] = line.split(":", 1)[1].strip()
    return images


def _environment_metadata(config: BenchmarkConfig, embedding_source: EmbeddingSource) -> dict[str, object]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "docker_images": _docker_images_from_compose(Path("docker-compose.yml")),
        "embedding_source": embedding_source.metadata,
        "backend_target": {
            "backend": config.backend,
            "qdrant_url": config.qdrant_url if config.backend == "qdrant" else None,
            "weaviate_url": config.weaviate_url if config.backend == "weaviate" else None,
            "pgvector_dsn": "[redacted]" if config.backend == "pgvector" else None,
        },
    }


def _stringify_error(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


def _safe_backend_info(backend: VectorBackend) -> dict[str, object]:
    try:
        return backend.backend_info()
    except Exception as exc:  # pragma: no cover - defensive path
        return {"name": backend.name, "error": _stringify_error(exc)}


def _run_embedding(
    embedding_source: EmbeddingSource,
    lifecycle: DocLifecycle,
    doc_id: str,
    text: str,
) -> list[float]:
    vector = embedding_source.get_vector(doc_id, text)
    lifecycle.monotonic_embedding_done = time.monotonic()
    lifecycle.t_embedding_done = now_utc()
    lifecycle.vector_dimensions = len(vector)
    return vector


def _upsert_document(
    backend: VectorBackend,
    preparation: _BackendPreparation,
    *,
    point_id: str,
    run_id: str,
    doc_id: str,
    text: str,
    source_ref: str | None,
    vector: list[float],
) -> None:
    preparation.ensure(len(vector))
    backend.upsert(
        point_id=point_id,
        vector=vector,
        payload={
            "run_id": run_id,
            "doc_id": doc_id,
            "text": text,
            "source_ref": source_ref,
        },
    )


def _run_write(
    backend: VectorBackend,
    preparation: _BackendPreparation,
    lifecycle: DocLifecycle,
    vector: list[float],
) -> list[float]:
    _upsert_document(
        backend,
        preparation,
        point_id=lifecycle.doc_id,
        run_id=lifecycle.run_id,
        doc_id=lifecycle.doc_id,
        text=lifecycle.text,
        source_ref=lifecycle.source_ref,
        vector=vector,
    )
    lifecycle.monotonic_write_acked = time.monotonic()
    lifecycle.t_write_acked = now_utc()
    return vector


def _preload_run_id(run_id: str) -> str:
    return f"{run_id}__preload"


def _run_preload_write(
    backend: VectorBackend,
    preparation: _BackendPreparation,
    run_id: str,
    doc_id: str,
    text: str,
    source_ref: str | None,
    vector: list[float],
) -> None:
    _upsert_document(
        backend,
        preparation,
        point_id=f"preload::{doc_id}",
        run_id=run_id,
        doc_id=doc_id,
        text=text,
        source_ref=source_ref,
        vector=vector,
    )


def _preload_documents(
    config: BenchmarkConfig,
    backend: VectorBackend,
    embedding_source: EmbeddingSource,
    preload_run_id: str,
    workload_docs: list,
) -> tuple[int, float]:
    if not workload_docs:
        return 0, 0.0

    start_monotonic = time.monotonic()
    preparation = _BackendPreparation(backend)
    final_futures: list[Future[None]] = []

    try:
        if embedding_source.dimensions is not None:
            preparation.ensure(embedding_source.dimensions)
        with ThreadPoolExecutor(max_workers=config.embedding_concurrency) as embed_pool, ThreadPoolExecutor(
            max_workers=config.write_concurrency
        ) as write_pool:
            for workload_doc in workload_docs:
                final_future: Future[None] = Future()
                final_futures.append(final_future)

                embed_future = embed_pool.submit(
                    embedding_source.get_vector,
                    workload_doc.doc_id,
                    workload_doc.text,
                )

                def on_embed_done(
                    future: Future[list[float]],
                    *,
                    workload_doc=workload_doc,
                    result_future: Future[None] = final_future,
                ) -> None:
                    try:
                        vector = future.result()
                    except BaseException as exc:  # pragma: no cover - executor edge
                        if not result_future.done():
                            result_future.set_exception(exc)
                        return

                    write_future = write_pool.submit(
                        _run_preload_write,
                        backend,
                        preparation,
                        preload_run_id,
                        workload_doc.doc_id,
                        workload_doc.text,
                        workload_doc.source_ref,
                        vector,
                    )

                    def on_write_done(
                        write_result: Future[None],
                        *,
                        result_future: Future[None] = result_future,
                    ) -> None:
                        try:
                            write_result.result()
                        except BaseException as exc:  # pragma: no cover - executor edge
                            if not result_future.done():
                                result_future.set_exception(exc)
                            return
                        if not result_future.done():
                            result_future.set_result(None)

                    write_future.add_done_callback(on_write_done)

                embed_future.add_done_callback(on_embed_done)

            for future in final_futures:
                future.result()
    except Exception:
        for future in final_futures:
            if future.done():
                continue
            future.cancel()
        raise

    return len(workload_docs), max(time.monotonic() - start_monotonic, 0.0)


def run_benchmark(
    config: BenchmarkConfig,
    *,
    backend_factory: BackendFactory = build_backend,
    embedding_source_factory: EmbeddingSourceFactory | None = None,
) -> RunSummary:
    output_dir = Path(config.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    embedding_source = (
        embedding_source_factory(config)
        if embedding_source_factory is not None
        else CachedEmbeddingSource(config.embedding_cache) if config.embedding_cache
        else build_embedding_source(
            embedding_mode=config.embedding_mode,
            provider=config.provider,
            base_url=config.base_url,
            model=config.embedding_model,
            dimensions=config.embedding_dimensions,
        )
    )
    try:
        backend = backend_factory(config)
    except Exception:
        embedding_source.close()
        raise
    preparation = _BackendPreparation(backend)
    scheduler = VisibilityScheduler(backend, config)
    records: list[DocLifecycle] = []
    final_futures: list[Future[DocLifecycle]] = []
    preload_run_id = _preload_run_id(config.run_id) if config.preload_docs else None
    preload_workload_docs = []
    workload_docs = []
    preload_backend: VectorBackend | None = None
    preload_written = 0
    preload_wall_clock_s: float | None = None

    def resolve_failure(result_future: Future[DocLifecycle], lifecycle: DocLifecycle, exc: BaseException) -> None:
        lifecycle.mark_error(_stringify_error(exc))
        if not result_future.done():
            result_future.set_result(lifecycle)

    try:
        preload_workload_docs = load_workload_docs(config, count=config.preload_docs)
        workload_docs = load_workload_docs(config, offset=config.preload_docs, count=config.docs)
        if preload_run_id is not None:
            preload_config = replace(config, run_id=preload_run_id)
            preload_backend = backend_factory(preload_config)
            preload_written, preload_wall_clock_s = _preload_documents(
                config,
                preload_backend,
                embedding_source,
                preload_run_id,
                preload_workload_docs,
            )

        # A deterministic readiness sample checks searchable preloads before measurement.
        if preload_workload_docs:
            stride = max(1, len(preload_workload_docs)//32)
            for doc in preload_workload_docs[::stride][:32]:
                vector = embedding_source.get_vector(doc.doc_id, doc.text)
                deadline = time.monotonic() + config.max_wait_s
                while not match_doc_in_hits(preload_backend.search(vector, config.top_k), doc.doc_id):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Preload readiness sample failed")
                    time.sleep(config.poll_interval_ms/1000)
        if len({d.doc_id for d in preload_workload_docs + workload_docs}) != len(preload_workload_docs + workload_docs):
            raise ValueError("Duplicate IDs across preload and measured documents")
        if config.embedding_cache:
            for doc in preload_workload_docs + workload_docs:
                embedding_source.get_vector(doc.doc_id, doc.text)
        if embedding_source.dimensions is not None:
            preparation.ensure(embedding_source.dimensions)
        started_at = now_utc()
        start_monotonic = time.monotonic()
        interval = 1.0 / config.rate
        with ThreadPoolExecutor(max_workers=config.embedding_concurrency) as embed_pool, ThreadPoolExecutor(
            max_workers=config.write_concurrency
        ) as write_pool:
            for idx, workload_doc in enumerate(workload_docs, start=1):
                scheduled = start_monotonic + ((idx - 1) * interval)
                sleep_for = scheduled - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                lifecycle = DocLifecycle(
                    run_id=config.run_id,
                    backend=config.backend,
                    embedding_mode=config.embedding_mode,
                    workload=config.workload,
                    doc_id=workload_doc.doc_id,
                    doc_num=workload_doc.doc_num,
                    text=workload_doc.text,
                    source_text=workload_doc.source_text,
                    source_ref=workload_doc.source_ref,
                    t_submitted=now_utc(),
                    monotonic_submitted=time.monotonic(),
                    scheduled_delay_ms=max(0, (time.monotonic()-scheduled)*1000),
                )
                records.append(lifecycle)

                final_future: Future[DocLifecycle] = Future()
                final_futures.append(final_future)

                embed_future = embed_pool.submit(
                    _run_embedding,
                    embedding_source,
                    lifecycle,
                    workload_doc.doc_id,
                    workload_doc.text,
                )

                def on_embed_done(
                    future: Future[list[float]],
                    *,
                    lifecycle: DocLifecycle = lifecycle,
                    result_future: Future[DocLifecycle] = final_future,
                ) -> None:
                    try:
                        vector = future.result()
                    except BaseException as exc:  # pragma: no cover - executor edge
                        resolve_failure(result_future, lifecycle, exc)
                        return

                    write_future = write_pool.submit(
                        _run_write,
                        backend,
                        preparation,
                        lifecycle,
                        vector,
                    )

                    def on_write_done(
                        write_result: Future[list[float]],
                        *,
                        lifecycle: DocLifecycle = lifecycle,
                        result_future: Future[DocLifecycle] = result_future,
                    ) -> None:
                        try:
                            written_vector = write_result.result()
                        except BaseException as exc:  # pragma: no cover - executor edge
                            resolve_failure(result_future, lifecycle, exc)
                            return

                        poll_future = scheduler.submit(lifecycle, written_vector)

                        def on_poll_done(
                            poll_result: Future[DocLifecycle],
                            *,
                            lifecycle: DocLifecycle = lifecycle,
                            result_future: Future[DocLifecycle] = result_future,
                        ) -> None:
                            try:
                                completed = poll_result.result()
                            except BaseException as exc:  # pragma: no cover - executor edge
                                resolve_failure(result_future, lifecycle, exc)
                                return
                            if not result_future.done():
                                result_future.set_result(completed)

                        poll_future.add_done_callback(on_poll_done)

                    write_future.add_done_callback(on_write_done)

                embed_future.add_done_callback(on_embed_done)

            submission_elapsed = max(time.monotonic() - start_monotonic, 1e-9)
            for future in final_futures:
                future.result()
            completion_elapsed = max(time.monotonic() - start_monotonic, 1e-9)
    finally:
        scheduler.close()
        backend_info = _safe_backend_info(backend)
        environment = _environment_metadata(config, embedding_source)
        embedding_source.close()
        if preload_backend is not None:
            preload_backend.close()
        backend.close()

    finished_at = now_utc()
    public_config = asdict(config)
    public_config["pgvector_dsn"] = "[redacted]"
    environment["schema_version"] = "1.0"
    environment["cpu_count"] = __import__("os").cpu_count()
    environment["dataset_sha256"] = (hashlib.sha256(Path(config.dataset_path).read_bytes()).hexdigest()
                                      if config.dataset_path and Path(config.dataset_path).is_file() else None)
    try:
        environment["git_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        environment["git_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        environment["git_revision"] = None
    summary = summarize(
        records=records,
        config=public_config,
        backend_info=backend_info,
        environment=environment,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        wall_clock_s=completion_elapsed,
        actual_submission_rate=((len(workload_docs)-1) / submission_elapsed if len(workload_docs)>1 else 0.0),
        actual_completion_rate=sum(r.status == "success" for r in records) / completion_elapsed,
        preload_written=preload_written,
        preload_wall_clock_s=preload_wall_clock_s,
        preload_run_id=preload_run_id,
    )
    summary.diagnostics = {
        "scheduled_delay_ms": metric_stats([r.scheduled_delay_ms for r in records]),
        "first_probe_queue_ms": metric_stats([r.search_queue_ms for r in records if r.search_queue_ms is not None]),
        "latency_population": "successful observations only; always read with success_rate",
        "observation": "upper bound on first retrievability; no absence guarantee from negative ANN probes",
        "deadline_origin": "submission",
    }
    write_trace_jsonl(output_dir / "trace.jsonl", records)
    write_metrics_csv(output_dir / "metrics.csv", records)
    write_summary_json(output_dir / "summary.json", summary)
    generate_html_report(run_dir=output_dir)
    print_summary(summary)
    return summary


def run_compare(
    config: CompareConfig,
    *,
    backend_factory: BackendFactory = build_backend,
    embedding_source_factory: EmbeddingSourceFactory | None = None,
) -> CompareSummary:
    compare_dir = Path(config.out_dir)
    compare_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for embedding_mode in config.embedding_modes:
        for backend in config.backends:
            for rate in config.rates:
                rate_label = str(rate).replace(".", "_")
                run_id = f"{config.compare_id}-{backend}-{embedding_mode}-r{rate_label}"
                run_dir = compare_dir / "runs" / run_id
                run_config = replace(
                    config.base_run_config,
                    run_id=run_id,
                    backend=backend,
                    rate=rate,
                    embedding_mode=embedding_mode,
                    out_dir=str(run_dir),
                )
                summary = run_benchmark(
                    run_config,
                    backend_factory=backend_factory,
                    embedding_source_factory=embedding_source_factory,
                )
                rows.append(
                    compare_row_from_summary(
                        compare_id=config.compare_id,
                        summary=summary,
                        rate=rate,
                        run_dir=str(run_dir),
                    )
                )

    compare_summary = CompareSummary(
        compare_id=config.compare_id,
        generated_at=now_utc().isoformat(),
        rows=rows,
        config={
            "backends": config.backends,
            "rates": config.rates,
            "embedding_modes": config.embedding_modes,
            "base_run_config": {**asdict(config.base_run_config), "pgvector_dsn": "[redacted]"},
        },
    )
    write_compare_summary_json(compare_dir / "comparison.json", compare_summary)
    write_compare_csv(compare_dir / "comparison.csv", rows)
    generate_comparison_html_report(
        comparison_json=compare_dir / "comparison.json",
        out_file=compare_dir / "comparison.html",
    )
    return compare_summary
