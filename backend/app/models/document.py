"""PostgreSQL system-of-record models for managed document ingestion."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class DocumentLifecycleStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class StorageStatus(str, enum.Enum):
    STORED = "STORED"
    RETAINED = "RETAINED"
    DELETED = "DELETED"


class IngestionStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    CHUNKING = "CHUNKING"
    CHUNKED = "CHUNKED"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED_FROM_INDEX = "DELETED_FROM_INDEX"


class IngestionJobType(str, enum.Enum):
    # PIPELINE remains readable for jobs created before staged ingestion.
    PIPELINE = "PIPELINE"
    PARSE_DOCUMENT = "PARSE_DOCUMENT"
    CHUNK_DOCUMENT = "CHUNK_DOCUMENT"
    EMBED_AND_INDEX = "EMBED_AND_INDEX"
    DELETE_FROM_INDEX = "DELETE_FROM_INDEX"
    REINDEX_DOCUMENT = "REINDEX_DOCUMENT"


class IngestionJobState(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    CANCELLED = "CANCELLED"
    # Legacy values remain readable during non-destructive migration.
    RUNNING = "RUNNING"
    RETRY = "RETRY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Document(Entity):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_key", name="uq_documents_tenant_document_key"),
        Index("ix_documents_tenant_status", "tenant_id", "lifecycle_status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    # connector_id is retained as the compatibility name for the most recent
    # producer. It is provenance, not ownership, and may be cleared when that
    # producer record is explicitly removed.
    connector_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("managed_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_connector_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("managed_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_seen_by_connector_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("managed_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_synchronized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    source_id: Mapped[str] = mapped_column(String(255))
    document_key: Mapped[str] = mapped_column(String(512))
    current_version_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    normalized_filename: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(20))
    lifecycle_status: Mapped[DocumentLifecycleStatus] = mapped_column(Enum(DocumentLifecycleStatus, name="document_lifecycle_status"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Entity):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "content_hash", name="uq_document_versions_document_hash"),
        Index("ix_document_versions_tenant_ingestion", "tenant_id", "ingestion_status"),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("managed_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(71))
    size_bytes: Mapped[int] = mapped_column(Integer)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    object_key: Mapped[str] = mapped_column(String(2048))
    storage_status: Mapped[StorageStatus] = mapped_column(Enum(StorageStatus, name="document_storage_status"))
    ingestion_status: Mapped[IngestionStatus] = mapped_column(Enum(IngestionStatus, name="document_ingestion_status"), index=True)
    parser_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    detected_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    format_detection_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    format_detection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parsing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunking_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJob(Entity):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_claim", "state", "next_retry_at", "created_at"),
        Index("ix_ingestion_jobs_tenant_state", "tenant_id", "state"),
        Index(
            "uq_ingestion_jobs_active_version_stage", "version_id", "job_type",
            unique=True,
            postgresql_where=text(
                "version_id IS NOT NULL AND state IN "
                "('PENDING','IN_PROGRESS','FAILED_RETRYABLE','RUNNING','RETRY')"
            ),
            sqlite_where=text(
                "version_id IS NOT NULL AND state IN "
                "('PENDING','IN_PROGRESS','FAILED_RETRYABLE','RUNNING','RETRY')"
            ),
        ),
        Index(
            "uq_ingestion_jobs_active_document_delete", "document_id",
            unique=True,
            postgresql_where=text(
                "job_type = 'DELETE_FROM_INDEX' AND state IN "
                "('PENDING','IN_PROGRESS','FAILED_RETRYABLE','RUNNING','RETRY')"
            ),
            sqlite_where=text(
                "job_type = 'DELETE_FROM_INDEX' AND state IN "
                "('PENDING','IN_PROGRESS','FAILED_RETRYABLE','RUNNING','RETRY')"
            ),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=True, index=True)
    job_type: Mapped[IngestionJobType] = mapped_column(Enum(IngestionJobType, name="ingestion_job_type"))
    state: Mapped[IngestionJobState] = mapped_column(Enum(IngestionJobState, name="ingestion_job_state"), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DocumentChunk(Entity):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("version_id", "chunk_index", name="uq_document_chunks_version_index"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("managed_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_key: Mapped[str] = mapped_column(String(255), unique=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    qdrant_point_id: Mapped[UUID] = mapped_column(unique=True)


class DocumentParsedSection(Entity):
    __tablename__ = "document_parsed_sections"
    __table_args__ = (
        UniqueConstraint("version_id", "section_index", name="uq_document_parsed_sections_version_index"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    section_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    section_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class DocumentIdempotencyRecord(Entity):
    __tablename__ = "document_idempotency_records"
    __table_args__ = (UniqueConstraint("tenant_id", "connector_id", "idempotency_key", name="uq_document_idempotency_scope"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[UUID] = mapped_column(ForeignKey("managed_connectors.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(20))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    http_status: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentAuditEvent(Entity):
    __tablename__ = "document_audit_events"
    __table_args__ = (Index("ix_document_audit_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)


class IngestionWorkerHeartbeat(Entity):
    __tablename__ = "ingestion_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    current_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
