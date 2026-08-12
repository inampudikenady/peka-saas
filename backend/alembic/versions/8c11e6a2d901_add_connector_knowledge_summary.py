"""Add summary-only Local Knowledge Store heartbeat metadata.

Revision ID: 8c11e6a2d901
Revises: 4d2a6f9c8b10
"""

from alembic import op
import sqlalchemy as sa


revision = "8c11e6a2d901"
down_revision = "4d2a6f9c8b10"
branch_labels = None
depends_on = None


def _add(table: str) -> None:
    op.add_column(table, sa.Column("local_knowledge_store_status", sa.String(32), nullable=True))
    op.add_column(
        table,
        sa.Column("knowledge_document_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        table,
        sa.Column(
            "knowledge_indexed_chunk_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        table,
        sa.Column("last_knowledge_index_activity_at", sa.DateTime(timezone=True), nullable=True),
    )


def upgrade() -> None:
    _add("managed_connectors")
    _add("connector_heartbeats")


def downgrade() -> None:
    for table in ("connector_heartbeats", "managed_connectors"):
        op.drop_column(table, "last_knowledge_index_activity_at")
        op.drop_column(table, "knowledge_indexed_chunk_count")
        op.drop_column(table, "knowledge_document_count")
        op.drop_column(table, "local_knowledge_store_status")
