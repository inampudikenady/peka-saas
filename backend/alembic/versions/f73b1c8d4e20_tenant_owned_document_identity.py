"""Make document identity tenant-owned and retain connector provenance.

Revision ID: f73b1c8d4e20
Revises: e62a4c9d7f10
"""

from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f73b1c8d4e20"
down_revision: Union[str, Sequence[str], None] = "e62a4c9d7f10"
branch_labels = None
depends_on = None


def _drop_connector_fk(table_name: str) -> None:
    bind = op.get_bind()
    for foreign_key in sa.inspect(bind).get_foreign_keys(table_name):
        if foreign_key["constrained_columns"] == ["connector_id"]:
            op.drop_constraint(foreign_key["name"], table_name, type_="foreignkey")
            return


def _deduplicate_documents() -> None:
    """Collapse connector-scoped copies before enforcing tenant identity."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT d.id, d.tenant_id, d.document_key, d.connector_id, d.source_id,
                   d.created_by_connector_id, d.last_seen_by_connector_id,
                   d.last_synchronized_at,
                   d.filename, d.normalized_filename, d.relative_path, d.mime_type,
                   d.extension, d.updated_at, d.current_version_id,
                   v.ingestion_status AS current_status
            FROM documents d
            LEFT JOIN document_versions v ON v.id = d.current_version_id
            ORDER BY d.created_at, d.id
            """
        )
    ).mappings()
    groups = defaultdict(list)
    for row in rows:
        groups[(row["tenant_id"], row["document_key"])].append(row)

    for documents in groups.values():
        if len(documents) < 2:
            continue
        canonical = max(
            documents,
            key=lambda item: (
                item["current_status"] == "INDEXED",
                item["updated_at"],
            ),
        )
        canonical_id = canonical["id"]
        latest = max(documents, key=lambda item: item["updated_at"])
        for document in documents:
            versions = list(
                bind.execute(
                    sa.text(
                        "SELECT id, content_hash, ingestion_status, created_at "
                        "FROM document_versions WHERE document_id = :document_id"
                    ),
                    {"document_id": document["id"]},
                ).mappings()
            )
            if document["id"] == canonical_id:
                continue
            # Old acknowledgements contain the duplicate IDs in their JSON
            # payload. Expiring them is safer than replaying stale identities.
            bind.execute(
                sa.text(
                    "DELETE FROM document_idempotency_records "
                    "WHERE document_id = :duplicate_id"
                ),
                {"duplicate_id": document["id"]},
            )
            for version in versions:
                existing = bind.execute(
                    sa.text(
                        "SELECT id, ingestion_status FROM document_versions "
                        "WHERE document_id = :canonical_id AND content_hash = :content_hash"
                    ),
                    {
                        "canonical_id": canonical_id,
                        "content_hash": version["content_hash"],
                    },
                ).mappings().first()
                if existing:
                    bind.execute(
                        sa.text(
                            "UPDATE document_audit_events SET document_id = :canonical_id, "
                            "version_id = :existing_id WHERE version_id = :duplicate_id"
                        ),
                        {
                            "canonical_id": canonical_id,
                            "existing_id": existing["id"],
                            "duplicate_id": version["id"],
                        },
                    )
                    bind.execute(
                        sa.text("DELETE FROM ingestion_jobs WHERE version_id = :version_id"),
                        {"version_id": version["id"]},
                    )
                    bind.execute(
                        sa.text("DELETE FROM document_chunks WHERE version_id = :version_id"),
                        {"version_id": version["id"]},
                    )
                    bind.execute(
                        sa.text(
                            "DELETE FROM document_parsed_sections WHERE version_id = :version_id"
                        ),
                        {"version_id": version["id"]},
                    )
                    bind.execute(
                        sa.text("DELETE FROM document_versions WHERE id = :version_id"),
                        {"version_id": version["id"]},
                    )
                else:
                    bind.execute(
                        sa.text(
                            "UPDATE document_versions SET document_id = :canonical_id "
                            "WHERE id = :version_id"
                        ),
                        {
                            "canonical_id": canonical_id,
                            "version_id": version["id"],
                        },
                    )
                    for table in (
                        "document_chunks",
                        "document_parsed_sections",
                        "ingestion_jobs",
                        "document_audit_events",
                    ):
                        bind.execute(
                            sa.text(
                                f"UPDATE {table} SET document_id = :canonical_id "
                                "WHERE version_id = :version_id"
                            ),
                            {
                                "canonical_id": canonical_id,
                                "version_id": version["id"],
                            },
                        )
            bind.execute(
                sa.text("DELETE FROM ingestion_jobs WHERE document_id = :duplicate_id"),
                {"duplicate_id": document["id"]},
            )
            bind.execute(
                sa.text(
                    "UPDATE document_audit_events SET document_id = :canonical_id "
                    "WHERE document_id = :duplicate_id"
                ),
                {"canonical_id": canonical_id, "duplicate_id": document["id"]},
            )
            bind.execute(
                sa.text("DELETE FROM documents WHERE id = :duplicate_id"),
                {"duplicate_id": document["id"]},
            )

        surviving_versions = list(
            bind.execute(
                sa.text(
                    "SELECT id, ingestion_status, created_at FROM document_versions "
                    "WHERE document_id = :canonical_id"
                ),
                {"canonical_id": canonical_id},
            ).mappings()
        )
        current_version_id = (
            max(
                surviving_versions,
                key=lambda item: (
                    item["ingestion_status"] == "INDEXED",
                    item["created_at"],
                ),
            )["id"]
            if surviving_versions
            else None
        )
        bind.execute(
            sa.text(
                """
                UPDATE documents
                SET connector_id = :connector_id,
                    last_seen_by_connector_id = :connector_id,
                    last_synchronized_at = :updated_at,
                    source_id = :source_id,
                    filename = :filename, normalized_filename = :normalized_filename,
                    relative_path = :relative_path, mime_type = :mime_type,
                    extension = :extension, current_version_id = :current_version_id,
                    updated_at = :updated_at
                WHERE id = :canonical_id
                """
            ),
            {
                **dict(latest),
                "canonical_id": canonical_id,
                "current_version_id": current_version_id,
            },
        )


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("created_by_connector_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("last_seen_by_connector_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("last_synchronized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE documents SET created_by_connector_id = connector_id, "
        "last_seen_by_connector_id = connector_id, last_synchronized_at = updated_at"
    )

    _deduplicate_documents()
    op.drop_constraint("uq_documents_logical_identity", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_tenant_document_key",
        "documents",
        ["tenant_id", "document_key"],
    )

    for table in ("documents", "document_versions", "document_chunks"):
        _drop_connector_fk(table)
        op.alter_column(table, "connector_id", nullable=True)
        op.create_foreign_key(
            f"fk_{table}_connector_id_retained",
            table,
            "managed_connectors",
            ["connector_id"],
            ["id"],
            ondelete="SET NULL",
        )
    for column in ("created_by_connector_id", "last_seen_by_connector_id"):
        op.create_foreign_key(
            f"fk_documents_{column}",
            "documents",
            "managed_connectors",
            [column],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_documents_{column}", "documents", [column])
    op.create_index(
        "ix_documents_last_synchronized_at", "documents", ["last_synchronized_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_last_synchronized_at", table_name="documents")
    for column in ("last_seen_by_connector_id", "created_by_connector_id"):
        op.drop_index(f"ix_documents_{column}", table_name="documents")
        op.drop_constraint(f"fk_documents_{column}", "documents", type_="foreignkey")
    for table in ("document_chunks", "document_versions", "documents"):
        op.drop_constraint(
            f"fk_{table}_connector_id_retained", table, type_="foreignkey"
        )
        op.alter_column(table, "connector_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_connector_id_legacy",
            table,
            "managed_connectors",
            ["connector_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.drop_constraint(
        "uq_documents_tenant_document_key", "documents", type_="unique"
    )
    op.create_unique_constraint(
        "uq_documents_logical_identity",
        "documents",
        ["tenant_id", "connector_id", "source_id", "document_key"],
    )
    op.drop_column("documents", "last_synchronized_at")
    op.drop_column("documents", "last_seen_by_connector_id")
    op.drop_column("documents", "created_by_connector_id")
