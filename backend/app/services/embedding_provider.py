"""Embedding provider abstraction with explicit test and OpenAI-compatible implementations."""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicFakeEmbeddingProvider:
    name = "deterministic-fake"
    model = "sha256-test-only"

    def __init__(self, dimension: int = 32) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            material = b""
            counter = 0
            while len(material) < self.dimension * 4:
                material += hashlib.sha256(f"{counter}:{text}".encode()).digest()
                counter += 1
            values = [
                int.from_bytes(material[index:index + 4], "big") / 2**32 - 0.5
                for index in range(0, self.dimension * 4, 4)
            ]
            norm = math.sqrt(sum(value * value for value in values)) or 1
            vectors.append([value / norm for value in values])
        return vectors


class OpenAICompatibleEmbeddingProvider:
    name = "openai-compatible"

    def __init__(
        self, base_url: str, api_key: str | None, model: str, dimension: int,
        timeout: float = 30, batch_size: int = 64,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout = timeout
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            headers = (
                {"Authorization": f"Bearer {self.api_key}"}
                if self.api_key else {}
            )
            response = httpx.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json={"model": self.model, "input": texts[start:start + self.batch_size]},
                timeout=self.timeout,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise TransientEmbeddingError("Embedding provider is temporarily unavailable")
            response.raise_for_status()
            vectors.extend(item["embedding"] for item in response.json()["data"])
        if any(len(vector) != self.dimension for vector in vectors):
            raise EmbeddingDimensionError("Embedding provider returned an unexpected dimension")
        return vectors


class EmbeddingProviderNotConfigured(RuntimeError):
    pass


class DisabledEmbeddingProvider:
    name = "disabled"
    model = "not-configured"
    dimension = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderNotConfigured("Embedding provider is not configured")


class TransientEmbeddingError(RuntimeError):
    pass


class EmbeddingDimensionError(ValueError):
    pass
