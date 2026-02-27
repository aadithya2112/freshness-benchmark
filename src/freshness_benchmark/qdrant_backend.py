from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def match_doc_in_hits(hits: list[dict[str, Any]], doc_id: str) -> bool:
    for hit in hits:
        payload = hit.get("payload") or {}
        if payload.get("doc_id") == doc_id:
            return True
    return False


class QdrantBackend:
    def __init__(self, qdrant_url: str, collection: str) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self.collection = collection

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

    def ensure_collection(self, vector_size: int) -> None:
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
        if status < 400:
            return

        error_msg = str((body.get("status") or {}).get("error", body))
        if status == 409 and "already exists" in error_msg.lower():
            return
        raise RuntimeError(f"Qdrant ensure_collection error: HTTP {status}: {body}")

    def upsert(self, point_id: int, vector: list[float], payload: dict[str, Any]) -> None:
        body = {
            "points": [
                {
                    "id": point_id,
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
        }
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

    def close(self) -> None:
        return None
