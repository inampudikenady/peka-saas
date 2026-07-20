"""Add platform roles and one-time invites.

Revision ID: c8d6e9a4f210
Revises: 49fcf1214f3e
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c8d6e9a4f210"
down_revision: Union[str, Sequence[str], None] = "49fcf1214f3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = postgresql.ENUM("PLATFORM_ADMIN", "PLATFORM_READONLY", name="platform_admin_role", create_type=False)
    purpose = postgresql.ENUM("SETUP", "PASSWORD_RESET", name="platform_admin_invite_purpose", create_type=False)
    role.create(op.get_bind())
    purpose.create(op.get_bind())
    op.add_column(
        "platform_admin_users",
        sa.Column("role", role, server_default="PLATFORM_ADMIN", nullable=False),
    )
    op.alter_column("platform_admin_users", "password_hash", nullable=True)
    op.create_table(
        "platform_admin_invites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("purpose", purpose, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_platform_admin_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["platform_admin_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_platform_admin_id"], ["platform_admin_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_admin_invites_token_hash", "platform_admin_invites", ["token_hash"], unique=True)
    op.create_index("ix_platform_admin_invites_user_id", "platform_admin_invites", ["user_id"])
    op.create_index("ix_platform_admin_invites_created_by_platform_admin_id", "platform_admin_invites", ["created_by_platform_admin_id"])


def downgrade() -> None:
    op.drop_table("platform_admin_invites")
    op.alter_column("platform_admin_users", "password_hash", nullable=False)
    op.drop_column("platform_admin_users", "role")
    sa.Enum(name="platform_admin_invite_purpose").drop(op.get_bind())
    sa.Enum(name="platform_admin_role").drop(op.get_bind())
