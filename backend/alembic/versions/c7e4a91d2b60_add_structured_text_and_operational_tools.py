"""Add structured text metadata and short-lived operational tool RPC.

Revision ID: c7e4a91d2b60
Revises: b51d9f4a7e03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e4a91d2b60"
down_revision: Union[str, Sequence[str], None] = "b51d9f4a7e03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("detected_format", sa.String(50), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("source_format", sa.String(100), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("format_detection_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("format_detection_reason", sa.String(500), nullable=True),
    )

    op.create_table(
        "operational_tool_requests",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token_hash", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["tenant_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_tool_requests_tenant_id",
        "operational_tool_requests",
        ["tenant_id"],
    )
    op.create_index(
        "ix_operational_tool_requests_connector_id",
        "operational_tool_requests",
        ["connector_id"],
    )
    op.create_index(
        "ix_operational_tool_requests_created_by_user_id",
        "operational_tool_requests",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_operational_tool_requests_status",
        "operational_tool_requests",
        ["status"],
    )
    op.create_index(
        "ix_operational_tool_requests_expires_at",
        "operational_tool_requests",
        ["expires_at"],
    )
    op.create_index(
        "ix_operational_tool_requests_connector_status_expiry",
        "operational_tool_requests",
        ["connector_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_operational_tool_requests_tenant_created",
        "operational_tool_requests",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("operational_tool_requests")
    op.drop_column("document_versions", "format_detection_reason")
    op.drop_column("document_versions", "format_detection_confidence")
    op.drop_column("document_versions", "source_format")
    op.drop_column("document_versions", "detected_format")

