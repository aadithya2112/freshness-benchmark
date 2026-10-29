from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


def match_doc_in_hits(hits: list[dict[str, Any]], doc_id: str) -> bool:
    for hit in hits:
        payload = hit.get("payload") or {}
        if payload.get("doc_id") == doc_id:
            return True
    return False


class QdrantBackend:
    name = "qdrant"

    def __init__(self, qdrant_url: str, collection: str, run_id: str, search_scope: str = "run") -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self.collection = collection
        self.run_id = run_id
        self.search_scope = search_scope
        self._prepared = False

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._qdrant_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Qdrant API error: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Qdrant connection error: {exc.reason}") from exc

    def _request_with_status(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._qdrant_url}{path}"
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
            raise RuntimeError(f"Qdrant connection error: {exc.reason}") from exc

    def _normalize_point_id(self, point_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.run_id}:{point_id}"))

    def _create_collection(self, vector_size: int) -> None:
        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        }
        status, body = self._request_with_status(
            "PUT",
            f"/collections/{self.collection}",
            body=payload,
        )
        if status >= 400:
            raise RuntimeError(
                f"Qdrant prepare_run error: HTTP {status}: {body}"
            )

    def _delete_collection(self) -> None:
        status, body = self._request_with_status("DELETE", f"/collections/{self.collection}")
        if status >= 400 and status != 404:
            raise RuntimeError(f"Qdrant delete_collection error: HTTP {status}: {body}")

    def _collection_vector_size(self) -> int | None:
        body = self._request("GET", f"/collections/{self.collection}")
        vectors = (
            body.get("result", {})
            .get("config", {})
            .get("params", {})
            .get("vectors")
        )
        if isinstance(vectors, dict):
            if "size" in vectors:
                return int(vectors["size"])
            for value in vectors.values():
                if isinstance(value, dict) and "size" in value:
                    return int(value["size"])
        return None

    def prepare_run(self, vector_size: int) -> None:
        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        }
        status, body = self._request_with_status(
            "PUT",
            f"/collections/{self.collection}",
            body=payload,
        )
        if status >= 400:
            error_msg = str((body.get("status") or {}).get("error", body))
            if status == 409 and "already exists" in error_msg.lower():
                existing_size = self._collection_vector_size()
                if existing_size is not None and existing_size != vector_size:
                    raise ValueError("Existing collection has incompatible dimensions; use a new collection")
            else:
                raise RuntimeError(
                    f"Qdrant prepare_run error: HTTP {status}: {body}"
                )
        self.reset_run_data()
        self._prepared = True

    def reset_run_data(self) -> None:
        selector = {
            "filter": {
                "must": [
                    {
                        "key": "run_id",
                        "match": {
                            "value": self.run_id,
                        },
                    }
                ]
            }
        }
        self._request(
            "POST",
            f"/collections/{self.collection}/points/delete",
            body=selector,
            query={"wait": "true"},
        )

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        body = {
            "points": [
                {
                    "id": self._normalize_point_id(point_id),
                    "vector": vector,
                    "payload": payload,
                }
            ]
        }
        self._request(
            "PUT",
            f"/collections/{self.collection}/points",
            body=body,
            query={"wait": "true"},
        )

    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        query_payload = {
            "query": vector,
            "limit": limit,
            "with_payload": True,
            "filter": {
                "must": [
                    {
                        "key": "run_id",
                        "match": {
                            "value": self.run_id,
                        },
                    }
                ]
            },
        }
        if self.search_scope == "collection":
            query_payload.pop("filter")
        status, body = self._request_with_status(
            "POST",
            f"/collections/{self.collection}/points/query",
            body=query_payload,
        )
        if status == 404:
            fallback_payload = {
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                **({"filter": query_payload["filter"]} if "filter" in query_payload else {}),
            }
            body = self._request(
                "POST",
                f"/collections/{self.collection}/points/search",
                body=fallback_payload,
            )
        elif status >= 400:
            raise RuntimeError(f"Qdrant search error: {body}")

        result = body.get("result")
        if isinstance(result, dict):
            points = result.get("points")
            if isinstance(points, list):
                return points
            return []
        if isinstance(result, list):
            return result
        return []

    def backend_info(self) -> dict[str, Any]:
        try:
            body = self._request("GET", "/")
        except RuntimeError:
            return {"name": self.name, "url": self._qdrant_url}
        return {
            "name": self.name,
            "url": self._qdrant_url,
            "version": body.get("version"),
            "title": body.get("title"),
            "collection": self._request("GET", f"/collections/{self.collection}").get("result"),
            "write_wait": True,
            "search_scope": self.search_scope,
        }

    def close(self) -> None:
        return None
