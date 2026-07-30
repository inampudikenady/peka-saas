"""The only retrieval-facing abstraction for PEKA knowledge."""

import logging
from uuid import UUID

from sqlalchemy import select

from app.models.connector import ManagedConnector
from app.models.document import DocumentChunk, IngestionStatus
from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import (
    KnowledgeCitation, KnowledgeResult, SearchRequest, SearchResponse,
)
from app.services.embedding_provider import EmbeddingProvider
from app.services.vector_store import VectorStore


logger = logging.getLogger(__name__)


class KnowledgeFilterError(ValueError):
    pass


class KnowledgeService:
    """Retrieves active tenant knowledge without exposing Qdrant to consumers."""

    def __init__(
        self,
        repository: DocumentRepository,
        embeddings: EmbeddingProvider,
        vectors: VectorStore,
    ) -> None:
        self.repository = repository
        self.embeddings = embeddings
        self.vectors = vectors

    def _validate_filters(self, tenant_id: UUID, request: SearchRequest) -> None:
        connector_id = request.filters.connector_id
        if connector_id is not None:
            connector = self.repository.session.scalar(select(ManagedConnector).where(
                ManagedConnector.tenant_id == tenant_id, ManagedConnector.id == connector_id,
            ))
            if connector is None:
                logger.warning(
                    "Knowledge connector filter rejected",
                    extra={"tenant_id": str(tenant_id), "connector_id": str(connector_id)},
                )
                raise KnowledgeFilterError("Connector filter is not available for this tenant")
        if request.filters.document_id is not None:
            document = self.repository.get_document(tenant_id, request.filters.document_id)
            if document is None:
                logger.warning(
                    "Knowledge document filter rejected",
                    extra={"tenant_id": str(tenant_id),
                           "document_id": str(request.filters.document_id)},
                )
                raise KnowledgeFilterError("Document filter is not available for this tenant")
            if connector_id is not None and document.connector_id != connector_id:
                raise KnowledgeFilterError("Document and connector filters do not match")
            if request.filters.source_id and document.source_id != request.filters.source_id:
                raise KnowledgeFilterError("Document and source filters do not match")
        elif request.filters.source_id:
            source_document = self.repository.session.scalar(select(Document).where(
                Document.tenant_id == tenant_id,
                Document.source_id == request.filters.source_id,
                Document.is_deleted.is_(False),
                *([Document.connector_id == connector_id] if connector_id else []),
            ).limit(1))
            if source_document is None:
                raise KnowledgeFilterError("Source filter is not available for this tenant")

    def search(self, tenant_id: UUID, request: SearchRequest) -> SearchResponse:
        self._validate_filters(tenant_id, request)
        filters = {
            # Connector/source payload values are immutable indexing provenance
            # and can predate a replacement connector. Apply those mutable
            # filters against the tenant-owned document record below.
            "connector_id": "",
            "source_id": "",
            "document_id": str(request.filters.document_id) if request.filters.document_id else "",
            "lifecycle_status": "ACTIVE",
        }
        query_vector = self.embeddings.embed([request.query])[0]
        hits = self.vectors.search(tenant_id, query_vector, request.top_k, filters)
        results: list[KnowledgeResult] = []
        for hit in hits:
            payload = hit.payload
            try:
                document_id = UUID(payload["document_id"])
                version_id = UUID(payload["version_id"])
                chunk_id = UUID(payload["chunk_id"])
            except (KeyError, TypeError, ValueError):
                continue
            document = self.repository.get_document(tenant_id, document_id)
            version = self.repository.get_version(tenant_id, version_id)
            chunk = self.repository.session.scalar(select(DocumentChunk).where(
                DocumentChunk.tenant_id == tenant_id, DocumentChunk.id == chunk_id,
                DocumentChunk.document_id == document_id, DocumentChunk.version_id == version_id,
            ))
            if (
                document is None or version is None or chunk is None or document.is_deleted
                or document.current_version_id != version.id
                or version.ingestion_status != IngestionStatus.INDEXED
                or (
                    request.filters.connector_id is not None
                    and document.last_seen_by_connector_id
                    != request.filters.connector_id
                )
                or (
                    request.filters.source_id is not None
                    and document.source_id != request.filters.source_id
                )
            ):
                continue
            connector = self.repository.session.scalar(select(ManagedConnector).where(
                ManagedConnector.tenant_id == tenant_id,
                ManagedConnector.id == document.connector_id,
            ))
            results.append(KnowledgeResult(
                knowledge_id=f"document:{chunk.id}", document_id=document.id,
                version_id=version.id, chunk_id=chunk.id, title=document.filename,
                text=chunk.text, score=hit.score,
                citation=KnowledgeCitation(
                    page_number=chunk.page_number, sheet_name=chunk.sheet_name,
                    row_start=chunk.row_start, row_end=chunk.row_end,
                    section_title=chunk.section_title,
                ),
                metadata={
                    "connector_id": str(document.connector_id),
                    "source_id": document.source_id,
                    "source_system": connector.name if connector else None,
                    "document_type": document.mime_type,
                    "revision": version.content_hash,
                    "ingested_at": (
                        version.indexed_at.isoformat()
                        if version.indexed_at else version.created_at.isoformat()
                    ),
                },
            ))
        logger.info(
            "Tenant knowledge search completed",
            extra={"tenant_id": str(tenant_id), "result_count": len(results)},
        )
        return SearchResponse(results=results)
