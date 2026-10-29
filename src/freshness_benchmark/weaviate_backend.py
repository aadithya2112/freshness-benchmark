from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from typing import Any


def _class_name(collection: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", collection).title().replace(" ", "")
    if not cleaned:
        cleaned = "FreshnessBenchmark"
    if not cleaned[0].isalpha():
        cleaned = f"Freshness{cleaned}"
    return cleaned


def _graphql_value(value: Any) -> str:
    if isinstance(value, dict):
        items = ", ".join(f"{key}: {_graphql_value(inner)}" for key, inner in value.items())
        return "{%s}" % items
    if isinstance(value, list):
        return "[%s]" % ", ".join(_graphql_value(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value))


class WeaviateBackend:
    name = "weaviate"

    def __init__(self, weaviate_url: str, collection: str, run_id: str, search_scope: str = "run") -> None:
        self._weaviate_url = weaviate_url.rstrip("/")
        self.collection = collection
        self.run_id = run_id
        self.search_scope = search_scope
        self.class_name = _class_name(collection)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._weaviate_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url=url,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                return response.status, parsed
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail) if detail else {}
            except json.JSONDecodeError:
                parsed = {"error": detail}
            return exc.code, parsed
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Weaviate connection error: {exc.reason}") from exc

    def _build_search_query(self, vector: list[float], limit: int) -> str:
        near_vector = _graphql_value({"vector": vector})
        where_filter = (
            "{path: [\"run_id\"], operator: Equal, valueText: "
            + json.dumps(self.run_id)
            + "}"
        )
        where_clause = f", where: {where_filter}" if self.search_scope == "run" else ""
        return (
            "{ Get { "
            f"{self.class_name}(nearVector: {near_vector}, limit: {limit}{where_clause}) "
            "{ doc_id run_id text _additional { id distance } } "
            "} }"
        )

    def prepare_run(self, vector_size: int) -> None:
        del vector_size
        schema = {
            "class": self.class_name,
            "vectorizer": "none",
            "properties": [
                {"name": "run_id", "dataType": ["text"]},
                {"name": "doc_id", "dataType": ["text"]},
                {"name": "text", "dataType": ["text"]},
                {"name": "source_ref", "dataType": ["text"]},
            ],
        }
        status, body = self._request("POST", "/v1/schema", body=schema)
        if status >= 400:
            messages = json.dumps(body)
            already_exists = "already exists" in messages.lower()
            if not already_exists:
                raise RuntimeError(f"Weaviate prepare_run error: HTTP {status}: {body}")
        self.reset_run_data()

    def reset_run_data(self) -> None:
        body = {
            "match": {
                "class": self.class_name,
                "where": {
                    "path": ["run_id"],
                    "operator": "Equal",
                    "valueText": self.run_id,
                },
            },
            "dryRun": False,
            "output": "verbose",
        }
        status, result = self._request("DELETE", "/v1/batch/objects", body=body)
        if status >= 400 and status != 422:
            raise RuntimeError(f"Weaviate reset_run_data error: HTTP {status}: {result}")

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        object_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.run_id}:{point_id}"))
        body = {
            "class": self.class_name,
            "id": object_id,
            "properties": payload,
            "vector": vector,
        }
        status, result = self._request("POST", "/v1/objects", body=body)
        if status >= 400:
            raise RuntimeError(f"Weaviate upsert error: HTTP {status}: {result}")

    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        query = self._build_search_query(vector, limit)
        status, result = self._request("POST", "/v1/graphql", body={"query": query})
        if status >= 400:
            raise RuntimeError(f"Weaviate search error: HTTP {status}: {result}")
        if result.get("errors"):
            raise RuntimeError(f"Weaviate search error: {result['errors']}")
        rows = result.get("data", {}).get("Get", {}).get(self.class_name, [])
        hits: list[dict[str, Any]] = []
        for row in rows:
            hits.append(
                {
                    "payload": {
                        "doc_id": row.get("doc_id"),
                        "run_id": row.get("run_id"),
                        "text": row.get("text"),
                    }
                }
            )
        return hits

    def backend_info(self) -> dict[str, Any]:
        status, result = self._request("GET", "/v1/meta")
        if status >= 400:
            return {"name": self.name, "url": self._weaviate_url}
        return {
            "name": self.name,
            "url": self._weaviate_url,
            "version": result.get("version"),
            "schema": self._request("GET", f"/v1/schema/{self.class_name}")[1],
            "search_scope": self.search_scope,
        }

    def close(self) -> None:
        return None
