from __future__ import annotations

import json
from pathlib import Path

from .models import BenchmarkConfig, WorkloadDoc


_PROFILE_FILLER = {
    "synthetic-small": 1,
    "synthetic-medium": 6,
    "synthetic-large": 20,
}

_TEXT_DIR_SUFFIXES = {".txt", ".md", ".markdown"}


def _anchor_for_doc_id(doc_id: str) -> str:
    return f"freshness-anchor-{doc_id}"


def _inject_anchor(source_text: str, anchor: str) -> str:
    return (
        f"{source_text.rstrip()}\n\n"
        f"Freshness benchmark retrieval anchor: {anchor}.\n"
        f"Use this marker to validate backend search visibility deterministically."
    )


def _synthetic_doc(doc_num: int, profile: str) -> WorkloadDoc:
    if profile not in _PROFILE_FILLER:
        raise ValueError(f"Unsupported workload profile: {profile}")

    doc_id = f"doc-{doc_num:06d}"
    anchor = _anchor_for_doc_id(doc_id)
    base = (
        f"This benchmark document is {doc_id}. "
        f"Use the unique retrieval anchor {anchor}. "
        f"Workload profile={profile}. Sequence={doc_num}. "
    )
    filler_repetitions = _PROFILE_FILLER[profile]
    filler = " ".join(
        f"Paragraph {i} for {doc_id} tracks deterministic freshness benchmarking."
        for i in range(1, filler_repetitions + 1)
    )
    text = f"{base}{filler}".strip()
    return WorkloadDoc(
        doc_num=doc_num,
        doc_id=doc_id,
        text=text,
        source_text=text,
        anchor=anchor,
    )


def _load_jsonl_dataset(
    config: BenchmarkConfig,
    *,
    offset: int,
    count: int,
) -> list[WorkloadDoc]:
    dataset_path = Path(config.dataset_path or "")
    text_field = config.text_field or ""
    docs: list[WorkloadDoc] = []
    skipped = 0
    with dataset_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            if skipped < offset:
                skipped += 1
                continue
            row = json.loads(raw)
            source_text = row.get(text_field)
            if not isinstance(source_text, str) or not source_text.strip():
                raise ValueError(
                    f"Dataset row {line_num} missing non-empty text field '{text_field}'"
                )
            if config.id_field:
                raw_id = row.get(config.id_field)
                if raw_id is None or str(raw_id).strip() == "":
                    raise ValueError(
                        f"Dataset row {line_num} missing id field '{config.id_field}'"
                    )
                doc_id = str(raw_id)
            else:
                doc_id = f"row-{line_num:06d}"
            anchor = _anchor_for_doc_id(doc_id)
            docs.append(
                WorkloadDoc(
                    doc_num=offset + len(docs) + 1,
                    doc_id=doc_id,
                    text=_inject_anchor(source_text, anchor),
                    source_text=source_text,
                    anchor=anchor,
                    source_ref=f"{dataset_path}:{line_num}",
                )
            )
            if len(docs) >= count:
                break
    if len(docs) < count:
        raise ValueError(
            f"Dataset workload produced {len(docs)} documents, but {count} are required after offset {offset}"
        )
    return docs


def _load_text_dir_dataset(
    config: BenchmarkConfig,
    *,
    offset: int,
    count: int,
) -> list[WorkloadDoc]:
    dataset_root = Path(config.dataset_path or "")
    candidates = sorted(
        path
        for path in dataset_root.rglob("*")
        if path.is_file() and path.suffix.lower() in _TEXT_DIR_SUFFIXES
    )
    sliced = candidates[offset : offset + count]
    if len(sliced) < count:
        raise ValueError(
            f"Dataset workload produced {len(sliced)} documents, but {count} are required after offset {offset}"
        )
    docs: list[WorkloadDoc] = []
    for path in sliced:
        source_text = path.read_text(encoding="utf-8")
        rel_path = path.relative_to(dataset_root).as_posix()
        doc_id = rel_path
        anchor = _anchor_for_doc_id(doc_id)
        docs.append(
            WorkloadDoc(
                doc_num=offset + len(docs) + 1,
                doc_id=doc_id,
                text=_inject_anchor(source_text, anchor),
                source_text=source_text,
                anchor=anchor,
                source_ref=rel_path,
            )
        )
    return docs


def load_workload_docs(
    config: BenchmarkConfig,
    *,
    offset: int = 0,
    count: int | None = None,
) -> list[WorkloadDoc]:
    requested = config.docs if count is None else count
    if requested < 0:
        raise ValueError("count must be >= 0")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if requested == 0:
        return []

    if config.workload in _PROFILE_FILLER:
        start = offset + 1
        stop = offset + requested + 1
        return [_synthetic_doc(doc_num, config.workload) for doc_num in range(start, stop)]

    if config.workload != "dataset":
        raise ValueError(f"Unsupported workload profile: {config.workload}")

    if config.dataset_format == "jsonl":
        docs = _load_jsonl_dataset(config, offset=offset, count=requested)
    elif config.dataset_format == "text-dir":
        docs = _load_text_dir_dataset(config, offset=offset, count=requested)
    else:
        raise ValueError(f"Unsupported dataset format: {config.dataset_format}")

    if not docs:
        raise ValueError("Dataset workload produced zero documents")
    return docs


def generate_workload_doc(doc_num: int, profile: str) -> WorkloadDoc:
    return _synthetic_doc(doc_num, profile)
