"""Safe, independently reported health checks for optional knowledge providers."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, settings
from app.services.embedding_provider import EmbeddingProviderNotConfigured
from app.services.provider_factory import embedding_provider, vector_store


def embedding_health(config: Settings = settings, verify: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "not_configured",
        "provider": config.peka_embedding_provider,
        "base_url": config.peka_embedding_base_url,
        "model": config.peka_embedding_model,
        "dimension": config.peka_embedding_dimension,
        "reason": "Embedding provider is not configured.",
    }
    if config.peka_embedding_provider == "disabled":
        return result
    try:
        provider = embedding_provider(config)
        if verify:
            vectors = provider.embed(["PEKA knowledge runtime health check"])
            actual_dimension = len(vectors[0]) if vectors else 0
            if actual_dimension != provider.dimension:
                return {
                    **result,
                    "status": "degraded",
                    "actual_dimension": actual_dimension,
                    "reason": "Embedding dimension does not match configuration.",
                }
        return {
            **result,
            "status": "healthy",
            "reason": None,
        }
    except EmbeddingProviderNotConfigured:
        return result
    except Exception:
        return {
            **result,
            "status": "unavailable",
            "reason": "Embedding endpoint is unreachable or rejected the health request.",
        }


def qdrant_health(config: Settings = settings) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "not_configured",
        "collection": config.peka_qdrant_collection,
        "point_count": None,
        "reason": "Qdrant is not configured.",
    }
    if not config.peka_qdrant_url:
        return result
    try:
        vectors = vector_store(config)
        if not vectors.health_check():
            raise RuntimeError("health check failed")
        vectors.ensure_collection(config.peka_embedding_dimension)
        point_count = vectors.count_all_points()
        return {
            **result,
            "status": "healthy",
            "point_count": point_count,
            "reason": None,
        }
    except Exception:
        return {
            **result,
            "status": "unavailable",
            "reason": (
                "Qdrant is unavailable or the collection embedding dimension "
                "does not match the worker configuration."
            ),
        }
