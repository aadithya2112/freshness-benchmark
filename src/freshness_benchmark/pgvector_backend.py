from __future__ import annotations

import json
import re
from typing import Any


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    if not cleaned:
        cleaned = "freshness_benchmark"
    if cleaned[0].isdigit():
        cleaned = f"fb_{cleaned}"
    return cleaned


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.12f}" for value in vector) + "]"


class PgvectorBackend:
    name = "pgvector"

    def __init__(self, dsn: str, collection: str, run_id: str) -> None:
        self._dsn = dsn
        self.collection = collection
        self.run_id = run_id
        self.table_name = _safe_identifier(collection)
        self._conn: Any | None = None

    def _connection(self) -> Any:
        if self._conn is not None:
            return self._conn
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dep
            raise RuntimeError(
                "pgvector backend requires the 'psycopg' package. Install project dependencies first."
            ) from exc
        self._conn = psycopg.connect(self._dsn, autocommit=True)
        return self._conn

    def prepare_run(self, vector_size: int) -> None:
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    embedding vector({vector_size}) NOT NULL
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table_name}_run_id_idx ON {self.table_name} (run_id)"
            )
            try:
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_embedding_hnsw_idx
                    ON {self.table_name}
                    USING hnsw (embedding vector_cosine_ops)
                    """
                )
            except Exception:
                # HNSW availability depends on the pgvector extension version. The
                # benchmark still works without the index for local reproducibility.
                conn.rollback()
        self.reset_run_data()

    def reset_run_data(self) -> None:
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self.table_name} WHERE run_id = %s",
                (self.run_id,),
            )

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.table_name} (id, run_id, doc_id, text, payload, embedding)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)
                ON CONFLICT (id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    doc_id = EXCLUDED.doc_id,
                    text = EXCLUDED.text,
                    payload = EXCLUDED.payload,
                    embedding = EXCLUDED.embedding
                """,
                (
                    point_id,
                    payload["run_id"],
                    payload["doc_id"],
                    payload["text"],
                    json.dumps(payload),
                    _vector_literal(vector),
                ),
            )

    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT payload
                FROM {self.table_name}
                WHERE run_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (self.run_id, _vector_literal(vector), limit),
            )
            rows = cur.fetchall()
        return [{"payload": row[0]} for row in rows]

    def backend_info(self) -> dict[str, Any]:
        conn = self._connection()
        info: dict[str, Any] = {"name": self.name}
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            info["postgres_version"] = cur.fetchone()[0]
            try:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                row = cur.fetchone()
                if row:
                    info["pgvector_version"] = row[0]
            except Exception:
                conn.rollback()
        return info

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
