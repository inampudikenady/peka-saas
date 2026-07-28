"""Tenant-admin document operations and tenant Knowledge Service search."""

import logging
from datetime import UTC, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import allow_tenant_user, require_tenant_admin
from app.api.dependencies import get_knowledge_service
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.document import (
    DocumentAuditEvent, DocumentChunk, DocumentLifecycleStatus,
    IngestionJobState, IngestionJobType, IngestionStatus,
)
from app.models.connector import ManagedConnector
from app.core.config import settings
from app.models.tenant_user import TenantUser
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import (
    DocumentListItem, DocumentVersionView, DocumentView, PipelineValidationResponse,
    SearchRequest, SearchResponse,
)
from app.services.embedding_provider import EmbeddingProviderNotConfigured
from app.services.knowledge_service import KnowledgeFilterError, KnowledgeService
from app.services.knowledge_pipeline_diagnostics import KnowledgePipelineDiagnostics
from app.services.provider_factory import embedding_provider, object_storage, vector_store


router = APIRouter(prefix="/tenant")
logger = logging.getLogger(__name__)


def _pipeline_state(version, chunk_count: int, is_deleted: bool) -> tuple[str, bool, bool]:
    if version is None:
        return "Pending", False, False
    if version.error_code == "NOT_CONFIGURED":
        embedding_status = "Not configured"
    elif version.embedding_provider and version.embedding_dimension:
        embedding_status = "Complete"
    elif version.ingestion_status == IngestionStatus.EMBEDDING:
        embedding_status = "Embedding"
    elif version.ingestion_status == IngestionStatus.FAILED:
        embedding_status = "Failed"
    else:
        embedding_status = "Pending"
    indexed = version.ingestion_status == IngestionStatus.INDEXED
    return embedding_status, indexed, indexed and chunk_count > 0 and not is_deleted


def _worker_state(repository: DocumentRepository) -> str:
    heartbeat = repository.latest_worker_heartbeat()
    if heartbeat is None:
        return "Not running"
    seen = heartbeat.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    age = (datetime.now(UTC) - seen).total_seconds()
    return (
        heartbeat.status.title()
        if age <= settings.peka_ingestion_worker_heartbeat_stale_seconds
        else "Stale"
    )


def _processing_state(
    repository: DocumentRepository, version, is_deleted: bool, document_id: UUID
) -> tuple[str, str | None]:
    if is_deleted:
        delete_job = repository.latest_job_for_document_stage(
            document_id, IngestionJobType.DELETE_FROM_INDEX
        )
        if delete_job is not None and delete_job.state in {
            IngestionJobState.PENDING,
            IngestionJobState.IN_PROGRESS,
            IngestionJobState.RUNNING,
        }:
            return "Delete pending", "Removal from PEKA knowledge is in progress."
        if delete_job is not None and delete_job.state in {
            IngestionJobState.FAILED_RETRYABLE,
            IngestionJobState.RETRY,
        }:
            return (
                "Delete retry required",
                "Removal from PEKA knowledge will be retried automatically.",
            )
        if delete_job is not None and delete_job.state in {
            IngestionJobState.FAILED,
            IngestionJobState.FAILED_PERMANENT,
        }:
            return "Delete failed", delete_job.safe_error_message
        return "Deleted", None
    if version is None:
        return "Queued", "The document version has not been created yet."
    active_job = repository.active_job_for_version(version.id)
    error_code = (
        active_job.error_code
        if active_job is not None and active_job.error_code
        else version.error_code
    )
    if error_code == "NOT_CONFIGURED":
        return "Blocked: embedding not configured", "Embedding provider is not configured."
    if error_code == "EMBEDDING_UNAVAILABLE":
        return "Blocked: embedding unavailable", "Embedding endpoint is unavailable."
    if error_code == "QDRANT_UNAVAILABLE":
        return "Blocked: Qdrant unavailable", "Qdrant is unavailable."
    if active_job is not None and active_job.state in {
        IngestionJobState.PENDING,
        IngestionJobState.FAILED_RETRYABLE,
        IngestionJobState.RETRY,
    }:
        return "Queued", None
    labels = {
        IngestionStatus.RECEIVED: "Queued",
        IngestionStatus.PARSING: "Parsing",
        IngestionStatus.PARSED: "Queued",
        IngestionStatus.CHUNKING: "Chunking",
        IngestionStatus.CHUNKED: "Queued",
        IngestionStatus.EMBEDDING: "Embedding",
        IngestionStatus.INDEXING: "Indexing",
        IngestionStatus.INDEXED: "Indexed",
        IngestionStatus.FAILED: "Failed",
        IngestionStatus.DELETE_PENDING: "Queued",
        IngestionStatus.DELETED_FROM_INDEX: "Deleted",
    }
    return labels[version.ingestion_status], version.safe_error_message


def _delete_eligibility(
    repository: DocumentRepository, document
) -> tuple[bool, str | None, bool]:
    delete_job = repository.active_job_for_document_stage(
        document.id, IngestionJobType.DELETE_FROM_INDEX
    )
    if delete_job is not None:
        return False, "Deletion is already in progress.", True
    if document.is_deleted:
        return False, "This document has already been deleted.", False
    if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE:
        return (
            False,
            "Document lifecycle metadata is invalid; ownership-safe deletion is unavailable.",
            False,
        )
    connector_tenant_id = repository.session.scalar(
        select(ManagedConnector.tenant_id).where(
            ManagedConnector.id == document.connector_id
        )
    )
    if connector_tenant_id != document.tenant_id:
        return (
            False,
            "Document connector ownership cannot be established safely.",
            False,
        )
    return True, None, False


def _version_view(version) -> DocumentVersionView | None:
    if version is None:
        return None
    return DocumentVersionView(
        id=version.id, content_hash=version.content_hash, size_bytes=version.size_bytes,
        ingestion_status=version.ingestion_status.value, storage_status=version.storage_status.value,
        parser_name=version.parser_name, chunker_name=version.chunker_name,
        embedding_provider=version.embedding_provider, embedding_model=version.embedding_model,
        received_at=version.received_at, indexed_at=version.indexed_at,
        error_code=version.error_code, error_message=version.safe_error_message,
    )


def _document_view(repository: DocumentRepository, document) -> DocumentView:
    version = repository.get_version(document.tenant_id, document.current_version_id) if document.current_version_id else None
    chunk_count = 0 if version is None else repository.session.scalar(
        select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.tenant_id == document.tenant_id, DocumentChunk.version_id == version.id
        )
    ) or 0
    versions = repository.list_versions(document.tenant_id, document.id)
    embedding_status, indexed, searchable = _pipeline_state(
        version, chunk_count, document.is_deleted
    )
    processing_status, blocking_reason = _processing_state(
        repository, version, document.is_deleted, document.id
    )
    delete_eligible, delete_unavailable_reason, deletion_in_progress = (
        _delete_eligibility(repository, document)
    )
    return DocumentView(
        id=document.id, connector_id=document.connector_id, source_id=document.source_id,
        document_key=document.document_key, filename=document.filename,
        relative_path=document.relative_path, mime_type=document.mime_type,
        is_deleted=document.is_deleted, current_version=_version_view(version),
        versions=[view for item in versions if (view := _version_view(item)) is not None],
        chunk_count=chunk_count, embedding_status=embedding_status,
        indexed=indexed, searchable=searchable,
        processing_status=processing_status,
        blocking_reason=blocking_reason,
        delete_eligible=delete_eligible,
        delete_unavailable_reason=delete_unavailable_reason,
        deletion_in_progress=deletion_in_progress,
        worker_status=_worker_state(repository),
        created_at=document.created_at, updated_at=document.updated_at,
    )


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(
    include_deleted: bool = Query(False),
    tenant: TenantContext = Depends(get_current_tenant_context),
    _user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    repository = DocumentRepository(db)
    response: list[DocumentListItem] = []
    for document in repository.list_documents(tenant.tenant_id, include_deleted):
        version = (
            repository.get_version(document.tenant_id, document.current_version_id)
            if document.current_version_id else None
        )
        chunk_count = 0 if version is None else repository.session.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.tenant_id == document.tenant_id,
                DocumentChunk.version_id == version.id,
            )
        ) or 0
        embedding_status, indexed, searchable = _pipeline_state(
            version, chunk_count, document.is_deleted
        )
        processing_status, blocking_reason = _processing_state(
            repository, version, document.is_deleted, document.id
        )
        delete_eligible, delete_unavailable_reason, deletion_in_progress = (
            _delete_eligibility(repository, document)
        )
        response.append(DocumentListItem(
            id=document.id, connector_id=document.connector_id,
            source_id=document.source_id, filename=document.filename,
            mime_type=document.mime_type,
            ingestion_status=(
                "DELETED" if document.is_deleted
                else version.ingestion_status.value if version else "RECEIVED"
            ),
            chunk_count=chunk_count, embedding_status=embedding_status,
            indexed=indexed, searchable=searchable,
            processing_status=processing_status,
            blocking_reason=blocking_reason,
            delete_eligible=delete_eligible,
            delete_unavailable_reason=delete_unavailable_reason,
            deletion_in_progress=deletion_in_progress,
            worker_status=_worker_state(repository),
            is_deleted=document.is_deleted, updated_at=document.updated_at,
        ))
    return response


@router.get("/documents/{document_id}", response_model=DocumentView)
def document_detail(
    document_id: UUID,
    tenant: TenantContext = Depends(get_current_tenant_context),
    _user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    repository = DocumentRepository(db)
    document = repository.get_document(tenant.tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _document_view(repository, document)


def _enqueue_document_job(
    repository: DocumentRepository,
    document,
    job_type: IngestionJobType,
    actor: TenantUser,
    action: str,
) -> DocumentView:
    version = (
        repository.get_version(document.tenant_id, document.current_version_id)
        if document.current_version_id else None
    )
    if job_type != IngestionJobType.DELETE_FROM_INDEX and version is None:
        raise HTTPException(status_code=409, detail="Document has no version to process.")
    active_job = (
        repository.active_job_for_document_stage(document.id, job_type)
        if job_type == IngestionJobType.DELETE_FROM_INDEX
        else repository.active_job_for_version(version.id)
        if version is not None
        else None
    )
    if active_job is None:
        repository.enqueue_job(
            document.tenant_id,
            document.id,
            version.id if version is not None else None,
            job_type,
        )
    repository.add(DocumentAuditEvent(
        tenant_id=document.tenant_id, document_id=document.id,
        version_id=version.id if version is not None else None,
        actor_user_id=actor.id, action=action,
    ))
    repository.commit()
    logger.info(
        "Tenant document action requested",
        extra={"tenant_id": str(document.tenant_id), "document_id": str(document.id),
               "stage": job_type.value, "action": action},
    )
    return _document_view(repository, document)


@router.post("/documents/{document_id}/retry", response_model=DocumentView)
def retry_document(
    document_id: UUID,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    repository = DocumentRepository(db)
    document = repository.get_document(tenant.tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    version = repository.get_version(tenant.tenant_id, document.current_version_id) if document.current_version_id else None
    blocked = bool(
        version
        and version.ingestion_status == IngestionStatus.CHUNKED
        and version.error_code
        in {"NOT_CONFIGURED", "EMBEDDING_UNAVAILABLE", "QDRANT_UNAVAILABLE"}
    )
    if version is None or (
        version.ingestion_status != IngestionStatus.FAILED and not blocked
    ):
        raise HTTPException(
            status_code=409,
            detail="Only failed or not-configured ingestion can be retried.",
        )
    has_chunks = bool(version and repository.list_chunks(tenant.tenant_id, version.id))
    if blocked or has_chunks:
        version.error_code = None
        version.safe_error_message = None
        return _enqueue_document_job(
            repository,
            document,
            IngestionJobType.EMBED_AND_INDEX,
            user,
            "RETRY_REQUESTED",
        )
    return _enqueue_document_job(
        repository, document, IngestionJobType.PARSE_DOCUMENT, user, "RETRY_REQUESTED"
    )


@router.post("/documents/{document_id}/reindex", response_model=DocumentView)
def reindex_document(
    document_id: UUID,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    repository = DocumentRepository(db)
    document = repository.get_document(tenant.tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.is_deleted:
        raise HTTPException(status_code=409, detail="Deleted documents cannot be re-indexed.")
    return _enqueue_document_job(
        repository, document, IngestionJobType.REINDEX_DOCUMENT, user, "REINDEX_REQUESTED"
    )


@router.delete("/documents/{document_id}", response_model=DocumentView)
def delete_document(
    document_id: UUID,
    connector_id: UUID | None = Query(None),
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    repository = DocumentRepository(db)
    document = repository.get_document_for_update(tenant.tenant_id, document_id)
    if document is None:
        logger.warning(
            "Tenant document deletion rejected",
            extra={
                "tenant_id": str(tenant.tenant_id),
                "document_id": str(document_id),
                "connector_id": str(connector_id) if connector_id else None,
                "status": "NOT_FOUND",
                "rejection_reason": "document_not_found",
            },
        )
        raise HTTPException(status_code=404, detail="Document not found.")
    if connector_id is not None and connector_id != document.connector_id:
        logger.warning(
            "Tenant document deletion rejected",
            extra={
                "tenant_id": str(tenant.tenant_id),
                "document_id": str(document.id),
                "connector_id": str(document.connector_id),
                "status": document.lifecycle_status.value,
                "rejection_reason": "connector_ownership_mismatch",
            },
        )
        raise HTTPException(
            status_code=403,
            detail="Document does not belong to the requested connector.",
        )
    eligible, reason, in_progress = _delete_eligibility(repository, document)
    if not eligible:
        status_code = 409 if document.is_deleted or in_progress else 422
        logger.warning(
            "Tenant document deletion rejected",
            extra={
                "tenant_id": str(tenant.tenant_id),
                "document_id": str(document.id),
                "connector_id": str(document.connector_id),
                "status": document.lifecycle_status.value,
                "rejection_reason": (
                    "delete_already_pending_or_complete"
                    if status_code == 409
                    else "invalid_legacy_ownership"
                ),
            },
        )
        raise HTTPException(status_code=status_code, detail=reason)
    document.is_deleted = True
    document.lifecycle_status = DocumentLifecycleStatus.DELETED
    document.deleted_at = datetime.now(UTC)
    return _enqueue_document_job(
        repository, document, IngestionJobType.DELETE_FROM_INDEX,
        user, "SOFT_DELETE_REQUESTED",
    )


@router.get(
    "/documents/{document_id}/pipeline-validation",
    response_model=PipelineValidationResponse,
)
def validate_document_pipeline(
    document_id: UUID,
    query: str = Query(..., min_length=1, max_length=2000),
    tenant: TenantContext = Depends(get_current_tenant_context),
    _user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    diagnostics = KnowledgePipelineDiagnostics(
        DocumentRepository(db),
        object_storage(),
        embedding_provider(),
        vector_store(),
    )
    return diagnostics.validate(tenant.tenant_id, document_id, query)


@router.post("/search", response_model=SearchResponse)
def search_documents(
    payload: SearchRequest,
    tenant: TenantContext = Depends(get_current_tenant_context),
    _user: TenantUser = Depends(allow_tenant_user),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
):
    try:
        return knowledge.search(tenant.tenant_id, payload)
    except (EmbeddingProviderNotConfigured, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Document search is not configured.") from exc
    except KnowledgeFilterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
