"""Add tenant-local password reset and development email capture.

Revision ID: a41c8e3f6d92
Revises: f73b1c8d4e20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a41c8e3f6d92"
down_revision: Union[str, Sequence[str], None] = "f73b1c8d4e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tenant_users",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "tenant_password_reset_tokens",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_platform_admin_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_user_id"], ["tenant_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requested_by_platform_admin_id"],
            ["platform_admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_tenant_password_reset_tokens_tenant_id",
        "tenant_password_reset_tokens",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tenant_password_reset_tokens_tenant_user_id",
        "tenant_password_reset_tokens",
        ["tenant_user_id"],
    )
    op.create_index(
        "ix_tenant_password_reset_tokens_token_hash",
        "tenant_password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_table(
        "development_emails",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("action_url", sa.Text(), nullable=False),
        sa.Column("delivery_state", sa.String(50), nullable=False, server_default="captured"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_development_emails_tenant_id", "development_emails", ["tenant_id"])
    op.create_index("ix_development_emails_recipient", "development_emails", ["recipient"])


def downgrade() -> None:
    op.drop_table("development_emails")
    op.drop_table("tenant_password_reset_tokens")
    op.drop_column("tenant_users", "locked")
    op.drop_column("tenant_users", "failed_login_attempts")
