"""Add document ingestion system-of-record tables.

Revision ID: a13f4c8d7e21
Revises: f0c91d7a4e22
"""

from alembic import op
import sqlalchemy as sa


revision = "a13f4c8d7e21"
down_revision = "f0c91d7a4e22"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    lifecycle = sa.Enum("ACTIVE", "DELETED", name="document_lifecycle_status")
    storage = sa.Enum("STORED", "RETAINED", "DELETED", name="document_storage_status")
    ingestion = sa.Enum(
        "RECEIVED", "PARSING", "PARSED", "CHUNKING", "CHUNKED", "EMBEDDING",
        "INDEXING", "INDEXED", "FAILED", "DELETE_PENDING", "DELETED_FROM_INDEX",
        name="document_ingestion_status",
    )
    job_type = sa.Enum("PIPELINE", "DELETE_FROM_INDEX", name="ingestion_job_type")
    job_state = sa.Enum("PENDING", "RUNNING", "RETRY", "COMPLETED", "FAILED", name="ingestion_job_state")

    op.create_table(
        "documents",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("document_key", sa.String(512), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("normalized_filename", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(20), nullable=False),
        sa.Column("lifecycle_status", lifecycle, nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connector_id", "source_id", "document_key", name="uq_documents_logical_identity"),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_connector_id", "documents", ["connector_id"])
    op.create_index("ix_documents_current_version_id", "documents", ["current_version_id"])
    op.create_index("ix_documents_tenant_status", "documents", ["tenant_id", "lifecycle_status"])

    op.create_table(
        "document_versions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("object_key", sa.String(2048), nullable=False),
        sa.Column("storage_status", storage, nullable=False),
        sa.Column("ingestion_status", ingestion, nullable=False),
        sa.Column("parser_name", sa.String(100), nullable=True),
        sa.Column("parser_version", sa.String(50), nullable=True),
        sa.Column("chunker_name", sa.String(100), nullable=True),
        sa.Column("chunker_version", sa.String(50), nullable=True),
        sa.Column("embedding_provider", sa.String(100), nullable=True),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parsing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chunking_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chunked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "content_hash", name="uq_document_versions_document_hash"),
    )
    for column in ("document_id", "tenant_id", "connector_id", "ingestion_status"):
        op.create_index(f"ix_document_versions_{column}", "document_versions", [column])
    op.create_index("ix_document_versions_tenant_ingestion", "document_versions", ["tenant_id", "ingestion_status"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("state", job_state, nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "document_id", "version_id", "state"):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])
    op.create_index("ix_ingestion_jobs_claim", "ingestion_jobs", ["state", "next_retry_at", "created_at"])

    op.create_table(
        "document_chunks",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_key", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("row_start", sa.Integer(), nullable=True),
        sa.Column("row_end", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("qdrant_point_id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_key"),
        sa.UniqueConstraint("qdrant_point_id"),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_document_chunks_version_index"),
    )
    for column in ("tenant_id", "document_id", "version_id"):
        op.create_index(f"ix_document_chunks_{column}", "document_chunks", [column])

    op.create_table(
        "document_idempotency_records",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connector_id", "idempotency_key", name="uq_document_idempotency_scope"),
    )
    op.create_index("ix_document_idempotency_records_tenant_id", "document_idempotency_records", ["tenant_id"])
    op.create_index("ix_document_idempotency_records_connector_id", "document_idempotency_records", ["connector_id"])


def downgrade() -> None:
    for table in (
        "document_idempotency_records", "document_chunks", "ingestion_jobs",
        "document_versions", "documents",
    ):
        op.drop_table(table)
    for enum_name in (
        "ingestion_job_state", "ingestion_job_type", "document_ingestion_status",
        "document_storage_status", "document_lifecycle_status",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
