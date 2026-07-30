"""Typed connector ingestion and tenant Knowledge Service contracts."""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx"}
SUPPORTED_MIME_TYPES = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".csv": {"text/csv", "application/csv", "application/octet-stream"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


class DocumentErrorCode(str, Enum):
    INVALID_CONNECTOR = "INVALID_CONNECTOR"
    CONNECTOR_RETIRED = "CONNECTOR_RETIRED"
    INVALID_DOCUMENT_METADATA = "INVALID_DOCUMENT_METADATA"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    HASH_MISMATCH = "HASH_MISMATCH"
    MIME_MISMATCH = "MIME_MISMATCH"
    INVALID_DOCUMENT_KEY = "INVALID_DOCUMENT_KEY"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class DocumentErrorResponse(BaseModel):
    code: DocumentErrorCode
    message: str


class ConnectorDocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    document_key: str = Field(min_length=1, max_length=512, pattern=r"^[^\\\x00]+$")
    relative_path: str = Field(min_length=1, max_length=1024)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-fA-F]{64}$")
    modified_at: datetime | None = None
    operation: Literal["upsert", "delete"]
    connector_version: str = Field(min_length=1, max_length=100)

    @field_validator("modified_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("modified_at must include a UTC offset")
        return value

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        from pathlib import Path

        if Path(value).name != value or Path(value).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("filename is unsafe or unsupported")
        return value

    @field_validator("document_key")
    @classmethod
    def safe_document_key(cls, value: str) -> str:
        from pathlib import PurePosixPath

        if ".." in PurePosixPath(value).parts:
            raise ValueError("document_key must not traverse directories")
        return value

    @model_validator(mode="after")
    def validate_mime_for_extension(self):
        from pathlib import Path

        extension = Path(self.filename).suffix.lower()
        if self.mime_type.lower() not in SUPPORTED_MIME_TYPES[extension]:
            raise ValueError("mime_type is not supported for filename extension")
        if self.operation == "upsert" and (
            self.content_hash is None or self.modified_at is None
        ):
            raise ValueError("upsert requires content_hash and modified_at")
        return self

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        from pathlib import PurePosixPath

        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("relative_path must not traverse directories")
        return value


class ConnectorDocumentAcknowledgement(BaseModel):
    accepted: bool = True
    document_id: UUID
    version_id: UUID | None
    content_hash: str | None
    ingestion_status: str


class ConnectorDocumentStatus(BaseModel):
    document_id: UUID
    version_id: UUID | None
    content_hash: str | None
    ingestion_status: str
    error_code: str | None = None
    error_message: str | None = None
    updated_at: datetime


class DocumentVersionView(BaseModel):
    id: UUID
    content_hash: str
    size_bytes: int
    ingestion_status: str
    storage_status: str
    parser_name: str | None
    detected_format: str | None
    source_format: str | None
    format_detection_confidence: float | None
    format_detection_reason: str | None
    chunker_name: str | None
    embedding_provider: str | None
    embedding_model: str | None
    received_at: datetime
    stored_at: datetime | None
    queued_at: datetime | None
    parsing_started_at: datetime | None
    parsed_at: datetime | None
    chunking_started_at: datetime | None
    chunked_at: datetime | None
    embedding_started_at: datetime | None
    embedding_completed_at: datetime | None
    indexing_started_at: datetime | None
    indexing_completed_at: datetime | None
    indexed_at: datetime | None
    error_code: str | None
    error_message: str | None


class DocumentView(BaseModel):
    id: UUID
    connector_id: UUID | None
    created_by_connector_id: UUID | None
    last_seen_by_connector_id: UUID | None
    last_synchronized_at: datetime | None
    source_freshness: str
    source_connector_name: str | None
    source_connector_status: str
    source_id: str
    document_key: str
    filename: str
    extension: str
    relative_path: str
    mime_type: str
    is_deleted: bool
    current_version: DocumentVersionView | None
    versions: list[DocumentVersionView] = Field(default_factory=list)
    chunk_count: int = 0
    embedding_status: str
    indexed: bool
    searchable: bool
    processing_status: str
    blocking_reason: str | None = None
    delete_eligible: bool
    delete_unavailable_reason: str | None = None
    deletion_in_progress: bool
    worker_status: str
    created_at: datetime
    updated_at: datetime


class DocumentListItem(BaseModel):
    id: UUID
    connector_id: UUID | None
    created_by_connector_id: UUID | None
    last_seen_by_connector_id: UUID | None
    last_synchronized_at: datetime | None
    source_freshness: str
    source_connector_name: str | None
    source_connector_status: str
    source_id: str
    filename: str
    extension: str
    mime_type: str
    detected_format: str | None = None
    source_format: str | None = None
    format_detection_confidence: float | None = None
    format_detection_reason: str | None = None
    ingestion_status: str
    chunk_count: int
    embedding_status: str
    indexed: bool
    searchable: bool
    processing_status: str
    blocking_reason: str | None = None
    delete_eligible: bool
    delete_unavailable_reason: str | None = None
    deletion_in_progress: bool
    worker_status: str
    is_deleted: bool
    updated_at: datetime


class IngestionHealthView(BaseModel):
    runtime_mode: str
    worker_status: str
    last_heartbeat_at: datetime | None
    runtime_started_at: datetime | None
    current_job_id: UUID | None
    queued_job_count: int
    processing_job_count: int
    failed_job_count: int
    latest_job_claimed_at: datetime | None
    latest_successful_job_at: datetime | None
    latest_safe_error: str | None
    embedding_status: str
    qdrant_status: str
    remediation: str | None


class SearchFilters(BaseModel):
    connector_id: UUID | None = None
    source_id: str | None = None
    document_id: UUID | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=25)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class KnowledgeCitation(BaseModel):
    page_number: int | None = None
    sheet_name: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    section_title: str | None = None


class KnowledgeResult(BaseModel):
    knowledge_id: str
    source_type: Literal["document"] = "document"
    text: str
    score: float
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    title: str
    citation: KnowledgeCitation
    metadata: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[KnowledgeResult]


class PipelineValidationResponse(BaseModel):
    tenant_id: UUID
    document_id: UUID
    version_id: UUID | None
    document_exists: bool
    object_exists: bool
    parsed_section_count: int
    chunk_count: int
    embeddings_exist: bool
    embedding_provider: str | None
    embedding_model: str | None
    qdrant_point_count: int | None
    knowledge_result_count: int | None
    expected_chunk_retrieved: bool
    searchable: bool
    ingestion_status: str | None
    issues: list[str] = Field(default_factory=list)
