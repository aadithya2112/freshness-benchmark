from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any, Protocol


class EmbeddingSource(Protocol):
    def get_vector(self, doc_id: str, text: str) -> list[float]:
        ...

    def close(self) -> None:
        ...

    @property
    def dimensions(self) -> int | None:
        ...

    @property
    def metadata(self) -> dict[str, Any]:
        ...


class LiveEmbeddingSource:
    def __init__(self, provider: str, base_url: str, model: str) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = self._resolve_api_key(provider)
        self._dimensions: int | None = None

    @staticmethod
    def _resolve_api_key(provider: str) -> str:
        provider_key_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        env_var = provider_key_map.get(provider.lower(), "OPENROUTER_API_KEY")
        value = os.getenv(env_var)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {env_var}")
        return value

    def get_vector(self, doc_id: str, text: str) -> list[float]:
        del doc_id
        payload: dict[str, Any] = {
            "model": self.model,
            "input": text,
        }
        request = urllib.request.Request(
            url=f"{self.base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Embedding API error: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Embedding API connection error: {exc.reason}") from exc

        body = json.loads(raw)
        data = body.get("data")
        if not data:
            raise RuntimeError("Embedding response missing 'data'")
        embedding = data[0].get("embedding")
        if not embedding:
            raise RuntimeError("Embedding response missing vector payload")
        self._dimensions = len(embedding)
        return embedding

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "type": "live",
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
        }

    def close(self) -> None:
        return None


class PrecomputedEmbeddingSource:
    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    @staticmethod
    def _float_from_digest(seed: bytes) -> float:
        value = int.from_bytes(seed[:8], "big", signed=False)
        return (value / float(2**64 - 1)) * 2.0 - 1.0

    def get_vector(self, doc_id: str, text: str) -> list[float]:
        # Hash both doc id and text so vectors stay deterministic across runs and
        # remain stable for fair backend comparisons.
        base = f"{doc_id}\n{text}".encode("utf-8")
        values: list[float] = []
        counter = 0
        while len(values) < self._dimensions:
            digest = hashlib.sha256(base + counter.to_bytes(4, "big")).digest()
            for offset in range(0, len(digest), 8):
                values.append(self._float_from_digest(digest[offset : offset + 8]))
                if len(values) == self._dimensions:
                    break
            counter += 1

        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "type": "precomputed",
            "dimensions": self._dimensions,
        }

    def close(self) -> None:
        return None


def build_embedding_source(
    *,
    embedding_mode: str,
    provider: str,
    base_url: str,
    model: str,
    dimensions: int,
) -> EmbeddingSource:
    if embedding_mode == "live":
        return LiveEmbeddingSource(provider=provider, base_url=base_url, model=model)
    if embedding_mode == "precomputed":
        return PrecomputedEmbeddingSource(dimensions=dimensions)
    raise ValueError(f"Unsupported embedding mode: {embedding_mode}")


class CachedEmbeddingSource:
    """Load and validate vectors before any timed operations."""
    def __init__(self, path: str) -> None:
        from pathlib import Path
        raw = Path(path).read_bytes()
        body = json.loads(raw)
        self._metadata = body["metadata"]
        self._vectors = body["vectors"]
        self._texts = body["text_sha256"]
        self._dimensions = int(self._metadata["dimensions"])
        if self._dimensions <= 0 or not self._vectors:
            raise ValueError("Empty embedding cache")
        for vector in self._vectors.values():
            if (len(vector) != self._dimensions or
                    not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector) or
                    sum(x*x for x in vector) == 0):
                raise ValueError("Invalid cached vector")
        self._metadata = {**self._metadata, "type": "cached_semantic",
                          "cache_sha256": hashlib.sha256(raw).hexdigest()}

    def get_vector(self, doc_id: str, text: str) -> list[float]:
        if hashlib.sha256(text.encode()).hexdigest() != self._texts.get(doc_id):
            raise ValueError(f"Embedding cache text mismatch: {doc_id}")
        return self._vectors[doc_id]

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    def close(self) -> None:
        pass
