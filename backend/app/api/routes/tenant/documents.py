"""Tenant-admin document operations and tenant Knowledge Service search."""

import logging
from datetime import UTC, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import allow_tenant_user, require_tenant_admin
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.document import (
    Document,
    DocumentAuditEvent,
    DocumentChunk,
    DocumentLifecycleStatus,
    DocumentVersion,
    IngestionJob,
    IngestionJobState,
    IngestionJobType,
    IngestionStatus,
)
from app.models.connector import ManagedConnector
from app.models.connector import ManagedConnectorStatus
from app.core.config import settings
from app.models.tenant_user import TenantUser
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import (
    DocumentListItem,
    DocumentVersionView,
    DocumentView,
    PipelineValidationResponse,
    IngestionHealthView,
    SearchRequest,
    SearchResponse,
)
from app.services.embedding_provider import EmbeddingProviderNotConfigured
from app.services.knowledge_service import KnowledgeFilterError, KnowledgeService
from app.services.knowledge_pipeline_diagnostics import KnowledgePipelineDiagnostics
from app.services.knowledge_runtime_health import embedding_health, qdrant_health
from app.services.provider_factory import (
    embedding_provider,
    object_storage,
    vector_store,
)
from app.services.ingestion_runtime import ingestion_runtime


router = APIRouter(prefix="/tenant")
logger = logging.getLogger(__name__)


def get_knowledge_service(db: Session = Depends(get_db)) -> KnowledgeService:
    """Build the retained migration-only knowledge service.

    This router is intentionally not registered by the normal SaaS application.
    Keeping the dependency local prevents customer-document providers from being
    initialized through the control-plane dependency module.
    """
    return KnowledgeService(
        DocumentRepository(db),
        embedding_provider(),
        vector_store(),
    )


def _pipeline_state(
    version, chunk_count: int, is_deleted: bool
) -> tuple[str, bool, bool]:
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
        return (
            "Blocked: embedding not configured",
            "Embedding provider is not configured.",
        )
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
    return True, None, False


def _source_freshness(repository: DocumentRepository, document) -> str:
    connector = (
        repository.session.get(ManagedConnector, document.last_seen_by_connector_id)
        if document.last_seen_by_connector_id
        else None
    )
    if connector is None:
        return "historical"
    if connector.status == ManagedConnectorStatus.RETIRED:
        return "stale"
    if connector.status in {
        ManagedConnectorStatus.OUT_OF_SYNC,
        ManagedConnectorStatus.DISCONNECTED,
        ManagedConnectorStatus.AUTHENTICATION_FAILED,
    }:
        return "stale"
    return "current"


def _source_connector(
    repository: DocumentRepository, document
) -> tuple[str | None, str]:
    connector = (
        repository.session.get(ManagedConnector, document.last_seen_by_connector_id)
        if document.last_seen_by_connector_id
        else None
    )
    if connector is None:
        return None, "historical"
    return connector.name, connector.status.value


def _tenant_vector_points_available(tenant_id: UUID) -> bool:
    store = vector_store()
    try:
        return store.count_points(tenant_id) > 0
    except Exception:
        return False
    finally:
        client = getattr(store, "client", None)
        if client is not None:
            client.close()


def _version_view(version) -> DocumentVersionView | None:
    if version is None:
        return None
    return DocumentVersionView(
        id=version.id,
        content_hash=version.content_hash,
        size_bytes=version.size_bytes,
        ingestion_status=version.ingestion_status.value,
        storage_status=version.storage_status.value,
        parser_name=version.parser_name,
        detected_format=version.detected_format,
        source_format=version.source_format,
        format_detection_confidence=version.format_detection_confidence,
        format_detection_reason=version.format_detection_reason,
        chunker_name=version.chunker_name,
        embedding_provider=version.embedding_provider,
        embedding_model=version.embedding_model,
        received_at=version.received_at,
        stored_at=version.stored_at,
        queued_at=version.queued_at,
        parsing_started_at=version.parsing_started_at,
        parsed_at=version.parsed_at,
        chunking_started_at=version.chunking_started_at,
        chunked_at=version.chunked_at,
        embedding_started_at=version.embedding_started_at,
        embedding_completed_at=version.embedding_completed_at,
        indexing_started_at=version.indexing_started_at,
        indexing_completed_at=version.indexing_completed_at,
        indexed_at=version.indexed_at,
        error_code=version.error_code,
        error_message=version.safe_error_message,
    )


def _document_view(
    repository: DocumentRepository,
    document,
    *,
    vector_points_available: bool | None = None,
) -> DocumentView:
    version = (
        repository.get_version(document.tenant_id, document.current_version_id)
        if document.current_version_id
        else None
    )
    chunk_count = (
        0
        if version is None
        else repository.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == document.tenant_id,
                DocumentChunk.version_id == version.id,
            )
        )
        or 0
    )
    versions = repository.list_versions(document.tenant_id, document.id)
    embedding_status, indexed, searchable = _pipeline_state(
        version, chunk_count, document.is_deleted
    )
    if indexed:
        if vector_points_available is None:
            vector_points_available = _tenant_vector_points_available(
                document.tenant_id
            )
        if not vector_points_available:
            searchable = False
    processing_status, blocking_reason = _processing_state(
        repository, version, document.is_deleted, document.id
    )
    source_freshness = _source_freshness(repository, document)
    source_connector_name, source_connector_status = _source_connector(
        repository, document
    )
    if processing_status == "Indexed":
        processing_status = f"Indexed / {source_freshness}"
    if indexed and not vector_points_available:
        processing_status = f"Indexed / {source_freshness} / vector index missing"
        blocking_reason = (
            "PostgreSQL contains indexed metadata, but the configured Qdrant "
            "collection has no searchable points. Re-index this document."
        )
    delete_eligible, delete_unavailable_reason, deletion_in_progress = (
        _delete_eligibility(repository, document)
    )
    return DocumentView(
        id=document.id,
        connector_id=document.connector_id,
        created_by_connector_id=document.created_by_connector_id,
        last_seen_by_connector_id=document.last_seen_by_connector_id,
        last_synchronized_at=document.last_synchronized_at,
        source_freshness=source_freshness,
        source_connector_name=source_connector_name,
        source_connector_status=source_connector_status,
        source_id=document.source_id,
        document_key=document.document_key,
        filename=document.filename,
        extension=document.extension,
        relative_path=document.relative_path,
        mime_type=document.mime_type,
        is_deleted=document.is_deleted,
        current_version=_version_view(version),
        versions=[
            view for item in versions if (view := _version_view(item)) is not None
        ],
        chunk_count=chunk_count,
        embedding_status=embedding_status,
        indexed=indexed,
        searchable=searchable,
        processing_status=processing_status,
        blocking_reason=blocking_reason,
        delete_eligible=delete_eligible,
        delete_unavailable_reason=delete_unavailable_reason,
        deletion_in_progress=deletion_in_progress,
        worker_status=_worker_state(repository),
        created_at=document.created_at,
        updated_at=document.updated_at,
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
    vector_points_available: bool | None = None
    for document in repository.list_documents(tenant.tenant_id, include_deleted):
        version = (
            repository.get_version(document.tenant_id, document.current_version_id)
            if document.current_version_id
            else None
        )
        chunk_count = (
            0
            if version is None
            else repository.session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.tenant_id == document.tenant_id,
                    DocumentChunk.version_id == version.id,
                )
            )
            or 0
        )
        embedding_status, indexed, searchable = _pipeline_state(
            version, chunk_count, document.is_deleted
        )
        if indexed:
            if vector_points_available is None:
                vector_points_available = _tenant_vector_points_available(
                    tenant.tenant_id
                )
            if not vector_points_available:
                searchable = False
        processing_status, blocking_reason = _processing_state(
            repository, version, document.is_deleted, document.id
        )
        source_freshness = _source_freshness(repository, document)
        source_connector_name, source_connector_status = _source_connector(
            repository, document
        )
        if processing_status == "Indexed":
            processing_status = f"Indexed / {source_freshness}"
        if indexed and not searchable:
            processing_status = f"Indexed / {source_freshness} / vector index missing"
            blocking_reason = (
                "PostgreSQL contains indexed metadata, but the configured Qdrant "
                "collection has no searchable points. Re-index this document."
            )
        delete_eligible, delete_unavailable_reason, deletion_in_progress = (
            _delete_eligibility(repository, document)
        )
        response.append(
            DocumentListItem(
                id=document.id,
                connector_id=document.connector_id,
                created_by_connector_id=document.created_by_connector_id,
                last_seen_by_connector_id=document.last_seen_by_connector_id,
                last_synchronized_at=document.last_synchronized_at,
                source_freshness=source_freshness,
                source_connector_name=source_connector_name,
                source_connector_status=source_connector_status,
                source_id=document.source_id,
                filename=document.filename,
                extension=document.extension,
                mime_type=document.mime_type,
                detected_format=version.detected_format if version else None,
                source_format=version.source_format if version else None,
                format_detection_confidence=(
                    version.format_detection_confidence if version else None
                ),
                format_detection_reason=(
                    version.format_detection_reason if version else None
                ),
                ingestion_status=(
                    "DELETED"
                    if document.is_deleted
                    else version.ingestion_status.value
                    if version
                    else "RECEIVED"
                ),
                chunk_count=chunk_count,
                embedding_status=embedding_status,
                indexed=indexed,
                searchable=searchable,
                processing_status=processing_status,
                blocking_reason=blocking_reason,
                delete_eligible=delete_eligible,
                delete_unavailable_reason=delete_unavailable_reason,
                deletion_in_progress=deletion_in_progress,
                worker_status=_worker_state(repository),
                is_deleted=document.is_deleted,
                updated_at=document.updated_at,
            )
        )
    return response


@router.get("/documents/ingestion-health", response_model=IngestionHealthView)
def ingestion_health(
    tenant: TenantContext = Depends(get_current_tenant_context),
    _user: TenantUser = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    repository = DocumentRepository(db)
    heartbeat = repository.latest_worker_heartbeat()
    active_states = [
        IngestionJobState.PENDING,
        IngestionJobState.FAILED_RETRYABLE,
        IngestionJobState.RETRY,
    ]
    processing_states = [IngestionJobState.IN_PROGRESS, IngestionJobState.RUNNING]
    failed_states = [IngestionJobState.FAILED, IngestionJobState.FAILED_PERMANENT]

    def count_for(states):
        return (
            db.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(
                    IngestionJob.tenant_id == tenant.tenant_id,
                    IngestionJob.state.in_(states),
                )
            )
            or 0
        )

    latest_claimed = db.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.tenant_id == tenant.tenant_id,
            IngestionJob.started_at.is_not(None),
        )
        .order_by(IngestionJob.started_at.desc())
        .limit(1)
    )
    latest_success = db.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.tenant_id == tenant.tenant_id,
            IngestionJob.state == IngestionJobState.SUCCEEDED,
        )
        .order_by(IngestionJob.completed_at.desc())
        .limit(1)
    )
    latest_failed = db.scalar(
        select(IngestionJob)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(DocumentVersion, DocumentVersion.id == IngestionJob.version_id)
        .where(
            IngestionJob.tenant_id == tenant.tenant_id,
            IngestionJob.state.in_(failed_states),
            Document.current_version_id == IngestionJob.version_id,
            Document.is_deleted.is_(False),
            DocumentVersion.error_code.is_not(None),
        )
        .order_by(IngestionJob.completed_at.desc(), IngestionJob.updated_at.desc())
        .limit(1)
    )
    worker_status = _worker_state(repository)
    embeddings = embedding_health(verify=False)
    vectors = qdrant_health()
    indexed_document_count = (
        db.scalar(
            select(func.count(func.distinct(Document.id)))
            .select_from(Document)
            .join(
                DocumentVersion,
                DocumentVersion.id == Document.current_version_id,
            )
            .join(
                DocumentChunk,
                DocumentChunk.version_id == DocumentVersion.id,
            )
            .where(
                Document.tenant_id == tenant.tenant_id,
                DocumentVersion.ingestion_status == IngestionStatus.INDEXED,
            )
        )
        or 0
    )
    failed_document_count = (
        db.scalar(
            select(func.count(func.distinct(Document.id)))
            .select_from(Document)
            .join(
                DocumentVersion,
                DocumentVersion.id == Document.current_version_id,
            )
            .where(
                Document.tenant_id == tenant.tenant_id,
                Document.is_deleted.is_(False),
                DocumentVersion.error_code.is_not(None),
            )
        )
        or 0
    )
    remediation = None
    if worker_status in {"Not running", "Stale", "Stopped"}:
        remediation = "Restart the PEKA backend; the in-process ingestion runtime starts with FastAPI."
    elif embeddings["status"] != "healthy":
        remediation = str(embeddings.get("reason") or "Check embedding configuration.")
    elif vectors["status"] != "healthy":
        remediation = str(vectors.get("reason") or "Start the local Qdrant service.")
    elif indexed_document_count > 0 and not _tenant_vector_points_available(
        tenant.tenant_id
    ):
        remediation = (
            "PostgreSQL has indexed document chunks but Qdrant has no points. "
            "Re-index the affected documents."
        )
        vectors["status"] = "degraded"
    return IngestionHealthView(
        runtime_mode=(
            "in_process"
            if heartbeat is not None and heartbeat.worker_id.startswith("in-process:")
            else "direct_python_process"
            if heartbeat is not None
            else "not_running"
        ),
        worker_status=worker_status,
        last_heartbeat_at=heartbeat.last_seen_at if heartbeat else None,
        runtime_started_at=heartbeat.created_at if heartbeat else None,
        current_job_id=heartbeat.current_job_id if heartbeat else None,
        queued_job_count=count_for(active_states),
        processing_job_count=count_for(processing_states),
        failed_job_count=failed_document_count,
        latest_job_claimed_at=latest_claimed.started_at if latest_claimed else None,
        latest_successful_job_at=latest_success.completed_at
        if latest_success
        else None,
        latest_safe_error=latest_failed.safe_error_message if latest_failed else None,
        embedding_status=str(embeddings["status"]),
        qdrant_status=str(vectors["status"]),
        remediation=remediation,
    )


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
        if document.current_version_id
        else None
    )
    if job_type != IngestionJobType.DELETE_FROM_INDEX and version is None:
        raise HTTPException(
            status_code=409, detail="Document has no version to process."
        )
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
    repository.add(
        DocumentAuditEvent(
            tenant_id=document.tenant_id,
            document_id=document.id,
            version_id=version.id if version is not None else None,
            actor_user_id=actor.id,
            action=action,
        )
    )
    repository.commit()
    ingestion_runtime.notify()
    logger.info(
        "Tenant document action requested",
        extra={
            "tenant_id": str(document.tenant_id),
            "document_id": str(document.id),
            "stage": job_type.value,
            "action": action,
        },
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
    version = (
        repository.get_version(tenant.tenant_id, document.current_version_id)
        if document.current_version_id
        else None
    )
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
        raise HTTPException(
            status_code=409, detail="Deleted documents cannot be re-indexed."
        )
    return _enqueue_document_job(
        repository,
        document,
        IngestionJobType.REINDEX_DOCUMENT,
        user,
        "REINDEX_REQUESTED",
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
        repository,
        document,
        IngestionJobType.DELETE_FROM_INDEX,
        user,
        "SOFT_DELETE_REQUESTED",
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
        raise HTTPException(
            status_code=503, detail="Document search is not configured."
        ) from exc
    except KnowledgeFilterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
