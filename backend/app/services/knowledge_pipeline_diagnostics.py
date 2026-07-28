"""Tenant-scoped diagnostics for the document-to-knowledge pipeline."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.models.document import (
    DocumentChunk,
    DocumentParsedSection,
    IngestionStatus,
)
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import (
    PipelineValidationResponse,
    SearchFilters,
    SearchRequest,
)
from app.services.embedding_provider import EmbeddingProvider
from app.services.knowledge_service import KnowledgeService
from app.services.object_storage import ObjectStorage
from app.services.vector_store import VectorStore


class KnowledgePipelineDiagnostics:
    def __init__(
        self,
        repository: DocumentRepository,
        storage: ObjectStorage,
        embeddings: EmbeddingProvider,
        vectors: VectorStore,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.embeddings = embeddings
        self.vectors = vectors

    def validate(
        self, tenant_id: UUID, document_id: UUID, query: str
    ) -> PipelineValidationResponse:
        issues: list[str] = []
        document = self.repository.get_document(tenant_id, document_id)
        if document is None:
            return PipelineValidationResponse(
                tenant_id=tenant_id,
                document_id=document_id,
                version_id=None,
                document_exists=False,
                object_exists=False,
                parsed_section_count=0,
                chunk_count=0,
                embeddings_exist=False,
                embedding_provider=None,
                embedding_model=None,
                qdrant_point_count=None,
                knowledge_result_count=None,
                expected_chunk_retrieved=False,
                searchable=False,
                ingestion_status=None,
                issues=["Document does not exist for this tenant."],
            )

        version = (
            self.repository.get_version(tenant_id, document.current_version_id)
            if document.current_version_id else None
        )
        object_exists = bool(version and self.storage.exists(version.object_key))
        if not object_exists:
            issues.append("Current version object is missing.")
        parsed_section_count = 0
        chunk_count = 0
        if version is not None:
            parsed_section_count = int(self.repository.session.scalar(
                select(func.count()).select_from(DocumentParsedSection).where(
                    DocumentParsedSection.tenant_id == tenant_id,
                    DocumentParsedSection.version_id == version.id,
                )
            ) or 0)
            chunk_count = int(self.repository.session.scalar(
                select(func.count()).select_from(DocumentChunk).where(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.version_id == version.id,
                )
            ) or 0)
        if parsed_section_count == 0:
            issues.append("No parsed sections exist.")
        if chunk_count == 0:
            issues.append("No chunks exist.")

        embeddings_exist = bool(
            version
            and version.embedding_provider
            and version.embedding_model
            and version.embedding_dimension
            and version.ingestion_status == IngestionStatus.INDEXED
        )
        if not embeddings_exist:
            issues.append("Embeddings are not recorded for the current version.")

        point_count: int | None = None
        try:
            point_count = self.vectors.count_points(
                tenant_id,
                document_id=document.id,
                version_id=version.id if version else None,
            )
            if point_count != chunk_count:
                issues.append("Qdrant point count does not match the current chunks.")
        except Exception:
            issues.append("Qdrant point count is unavailable.")

        knowledge_count: int | None = None
        expected_chunk_retrieved = False
        if version is not None:
            try:
                response = KnowledgeService(
                    self.repository, self.embeddings, self.vectors
                ).search(
                    tenant_id,
                    SearchRequest(
                        query=query,
                        top_k=25,
                        filters=SearchFilters(document_id=document.id),
                    ),
                )
                knowledge_count = len(response.results)
                expected_chunk_retrieved = any(
                    result.document_id == document.id
                    and result.version_id == version.id
                    for result in response.results
                )
                if not expected_chunk_retrieved:
                    issues.append("Knowledge Service did not retrieve the current version.")
            except Exception:
                issues.append("Knowledge Service retrieval is unavailable.")

        searchable = bool(
            not document.is_deleted
            and version
            and version.ingestion_status == IngestionStatus.INDEXED
            and chunk_count > 0
            and point_count == chunk_count
            and expected_chunk_retrieved
        )
        return PipelineValidationResponse(
            tenant_id=tenant_id,
            document_id=document.id,
            version_id=version.id if version else None,
            document_exists=True,
            object_exists=object_exists,
            parsed_section_count=parsed_section_count,
            chunk_count=chunk_count,
            embeddings_exist=embeddings_exist,
            embedding_provider=version.embedding_provider if version else None,
            embedding_model=version.embedding_model if version else None,
            qdrant_point_count=point_count,
            knowledge_result_count=knowledge_count,
            expected_chunk_retrieved=expected_chunk_retrieved,
            searchable=searchable,
            ingestion_status=version.ingestion_status.value if version else None,
            issues=issues,
        )
