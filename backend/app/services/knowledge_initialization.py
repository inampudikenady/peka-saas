"""Non-blocking startup initialization for optional knowledge dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings, settings
from app.services.provider_factory import vector_store


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeInitializationResult:
    status: str
    qdrant_configured: bool
    qdrant_connected: bool
    collection_ready: bool
    detail: str


def initialize_knowledge_dependencies(
    config: Settings = settings,
) -> KnowledgeInitializationResult:
    """Initialize Qdrant when configured, without blocking core SaaS startup."""
    if not config.peka_qdrant_url:
        result = KnowledgeInitializationResult(
            status="degraded",
            qdrant_configured=False,
            qdrant_connected=False,
            collection_ready=False,
            detail="Qdrant is not configured.",
        )
        logger.warning(
            "Knowledge services started in degraded mode",
            extra={
                "knowledge_status": result.status,
                "qdrant_status": "not_configured",
            },
        )
        return result

    try:
        vectors = vector_store(config)
        if not vectors.health_check():
            raise RuntimeError("Qdrant health check failed")
        vectors.ensure_collection(config.peka_embedding_dimension)
    except Exception as exc:
        result = KnowledgeInitializationResult(
            status="degraded",
            qdrant_configured=True,
            qdrant_connected=False,
            collection_ready=False,
            detail="Qdrant is unavailable or its collection is not ready.",
        )
        logger.warning(
            "Knowledge services started in degraded mode",
            extra={
                "knowledge_status": result.status,
                "qdrant_status": "unavailable",
                "error_type": type(exc).__name__,
            },
        )
        return result

    result = KnowledgeInitializationResult(
        status="healthy",
        qdrant_configured=True,
        qdrant_connected=True,
        collection_ready=True,
        detail="Qdrant collection and payload indexes are ready.",
    )
    logger.info(
        "Knowledge services initialized status=%s qdrant=healthy collection=%s "
        "embedding_dimension=%s",
        result.status,
        config.peka_qdrant_collection,
        config.peka_embedding_dimension,
    )
    return result
