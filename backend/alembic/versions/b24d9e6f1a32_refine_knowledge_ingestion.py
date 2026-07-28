"""Refine staged knowledge ingestion and operational audit.

Revision ID: b24d9e6f1a32
Revises: a13f4c8d7e21
"""

from alembic import op
import sqlalchemy as sa


revision = "b24d9e6f1a32"
down_revision = "a13f4c8d7e21"
branch_labels = None
depends_on = None


JOB_TYPES = (
    "PIPELINE", "PARSE_DOCUMENT", "CHUNK_DOCUMENT", "EMBED_AND_INDEX",
    "DELETE_FROM_INDEX", "REINDEX_DOCUMENT",
)
JOB_STATES = (
    "PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED_RETRYABLE",
    "FAILED_PERMANENT", "CANCELLED", "RUNNING", "RETRY", "COMPLETED", "FAILED",
)


def _replace_enum(table: str, column: str, name: str, values: tuple[str, ...]) -> None:
    old_name = f"{name}_old"
    op.execute(f"ALTER TYPE {name} RENAME TO {old_name}")
    sa.Enum(*values, name=name).create(op.get_bind())
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} "
        f"USING {column}::text::{name}"
    )
    op.execute(f"DROP TYPE {old_name}")


def upgrade() -> None:
    _replace_enum("ingestion_jobs", "job_type", "ingestion_job_type", JOB_TYPES)
    _replace_enum("ingestion_jobs", "state", "ingestion_job_state", JOB_STATES)
    op.alter_column("document_versions", "error_message", new_column_name="safe_error_message")

    op.add_column("document_chunks", sa.Column("connector_id", sa.Uuid(), nullable=True))
    op.add_column("document_chunks", sa.Column("source_id", sa.String(255), nullable=True))
    op.execute(
        "UPDATE document_chunks AS chunk SET connector_id = document.connector_id, "
        "source_id = document.source_id FROM documents AS document "
        "WHERE document.id = chunk.document_id"
    )
    op.alter_column("document_chunks", "connector_id", nullable=False)
    op.alter_column("document_chunks", "source_id", nullable=False)
    op.create_foreign_key(
        "fk_document_chunks_connector_id", "document_chunks", "managed_connectors",
        ["connector_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_document_chunks_connector_id", "document_chunks", ["connector_id"])
    op.create_index("ix_document_chunks_source_id", "document_chunks", ["source_id"])

    op.create_table(
        "document_parsed_sections",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("row_start", sa.Integer(), nullable=True),
        sa.Column("row_end", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "section_index", name="uq_document_parsed_sections_version_index"),
    )
    op.create_index("ix_document_parsed_sections_tenant_id", "document_parsed_sections", ["tenant_id"])
    op.create_index("ix_document_parsed_sections_document_id", "document_parsed_sections", ["document_id"])
    op.create_index("ix_document_parsed_sections_version_id", "document_parsed_sections", ["version_id"])

    op.add_column("document_idempotency_records", sa.Column("document_id", sa.Uuid(), nullable=True))
    op.add_column("document_idempotency_records", sa.Column("version_id", sa.Uuid(), nullable=True))
    op.add_column(
        "document_idempotency_records",
        sa.Column("http_status", sa.Integer(), server_default="201", nullable=False),
    )
    op.execute(
        "UPDATE document_idempotency_records SET "
        "document_id = NULLIF(response_payload->>'document_id', '')::uuid, "
        "version_id = NULLIF(response_payload->>'version_id', '')::uuid"
    )
    op.alter_column("document_idempotency_records", "http_status", server_default=None)
    op.create_foreign_key(
        "fk_document_idempotency_document_id", "document_idempotency_records", "documents",
        ["document_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_document_idempotency_version_id", "document_idempotency_records", "document_versions",
        ["version_id"], ["id"], ondelete="SET NULL",
    )

    op.create_index("ix_ingestion_jobs_tenant_state", "ingestion_jobs", ["tenant_id", "state"])
    op.create_index(
        "uq_ingestion_jobs_active_version_stage", "ingestion_jobs", ["version_id", "job_type"],
        unique=True,
        postgresql_where=sa.text(
            "version_id IS NOT NULL AND state IN "
            "('PENDING','IN_PROGRESS','FAILED_RETRYABLE','RUNNING','RETRY')"
        ),
    )

    op.create_table(
        "document_audit_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_audit_events_tenant_id", "document_audit_events", ["tenant_id"])
    op.create_index("ix_document_audit_events_document_id", "document_audit_events", ["document_id"])
    op.create_index("ix_document_audit_tenant_created", "document_audit_events", ["tenant_id", "created_at"])

    op.create_table(
        "ingestion_worker_heartbeats",
        sa.Column("worker_id", sa.String(255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_job_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["current_job_id"], ["ingestion_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_worker_heartbeats_worker_id", "ingestion_worker_heartbeats", ["worker_id"], unique=True)
    op.create_index("ix_ingestion_worker_heartbeats_last_seen_at", "ingestion_worker_heartbeats", ["last_seen_at"])


def downgrade() -> None:
    op.drop_table("ingestion_worker_heartbeats")
    op.drop_table("document_audit_events")
    op.drop_table("document_parsed_sections")
    op.drop_index("uq_ingestion_jobs_active_version_stage", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_tenant_state", table_name="ingestion_jobs")
    op.drop_constraint("fk_document_idempotency_version_id", "document_idempotency_records", type_="foreignkey")
    op.drop_constraint("fk_document_idempotency_document_id", "document_idempotency_records", type_="foreignkey")
    op.drop_column("document_idempotency_records", "http_status")
    op.drop_column("document_idempotency_records", "version_id")
    op.drop_column("document_idempotency_records", "document_id")
    op.drop_index("ix_document_chunks_source_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_connector_id", table_name="document_chunks")
    op.drop_constraint("fk_document_chunks_connector_id", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "source_id")
    op.drop_column("document_chunks", "connector_id")
    op.alter_column("document_versions", "safe_error_message", new_column_name="error_message")
    _replace_enum(
        "ingestion_jobs", "state", "ingestion_job_state",
        ("PENDING", "RUNNING", "RETRY", "COMPLETED", "FAILED"),
    )
    _replace_enum(
        "ingestion_jobs", "job_type", "ingestion_job_type", ("PIPELINE", "DELETE_FROM_INDEX")
    )
