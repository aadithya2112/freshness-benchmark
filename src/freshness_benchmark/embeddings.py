from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class EmbeddingClient:
    def __init__(self, provider: str, base_url: str, model: str) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = self._resolve_api_key(provider)

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

    def embed(self, text: str) -> list[float]:
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
        return embedding

    def close(self) -> None:
        return None
