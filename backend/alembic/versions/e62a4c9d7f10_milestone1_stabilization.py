"""Milestone 1 tenant, timezone, and ingestion diagnostics.

Revision ID: e62a4c9d7f10
Revises: d14e6a9c2b31
"""

from alembic import op
import sqlalchemy as sa


revision = "e62a4c9d7f10"
down_revision = "d14e6a9c2b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        "stored_at",
        "queued_at",
        "embedding_completed_at",
        "indexing_started_at",
        "indexing_completed_at",
    ):
        op.add_column(
            "document_versions",
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        """
        UPDATE document_versions
        SET stored_at = COALESCE(stored_at, received_at),
            queued_at = COALESCE(queued_at, received_at),
            indexing_completed_at = COALESCE(indexing_completed_at, indexed_at)
        """
    )
    op.execute(
        """
        UPDATE tenants
        SET timezone = CASE timezone
            WHEN 'Asia/Calcutta' THEN 'Asia/Kolkata'
            WHEN 'Etc/UTC' THEN 'UTC'
            WHEN 'Etc/GMT' THEN 'UTC'
            WHEN 'GMT' THEN 'UTC'
            ELSE timezone
        END
        """
    )
    op.create_table(
        "tenant_audit_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_slug", sa.String(100), nullable=False),
        sa.Column("tenant_display_name", sa.String(255), nullable=False),
        sa.Column("actor_platform_admin_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(100), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["actor_platform_admin_id"],
            ["platform_admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_audit_events_tenant_id", "tenant_audit_events", ["tenant_id"])
    op.create_index("ix_tenant_audit_events_tenant_slug", "tenant_audit_events", ["tenant_slug"])
    op.create_index("ix_tenant_audit_events_actor_platform_admin_id", "tenant_audit_events", ["actor_platform_admin_id"])
    op.create_index("ix_tenant_audit_events_action", "tenant_audit_events", ["action"])
    op.create_index(
        "ix_tenant_audit_slug_created",
        "tenant_audit_events",
        ["tenant_slug", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_audit_slug_created", table_name="tenant_audit_events")
    op.drop_index("ix_tenant_audit_events_action", table_name="tenant_audit_events")
    op.drop_index("ix_tenant_audit_events_actor_platform_admin_id", table_name="tenant_audit_events")
    op.drop_index("ix_tenant_audit_events_tenant_slug", table_name="tenant_audit_events")
    op.drop_index("ix_tenant_audit_events_tenant_id", table_name="tenant_audit_events")
    op.drop_table("tenant_audit_events")
    for column in (
        "indexing_completed_at",
        "indexing_started_at",
        "embedding_completed_at",
        "queued_at",
        "stored_at",
    ):
        op.drop_column("document_versions", column)
