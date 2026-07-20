"""Extend tenant invites for local user setup and reset.

Revision ID: eaf812c6b432
Revises: d9e7f1b5a321
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "eaf812c6b432"
down_revision = "d9e7f1b5a321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    purpose = postgresql.ENUM("BOOTSTRAP", "USER_SETUP", "PASSWORD_RESET", name="tenant_invite_purpose", create_type=False)
    purpose.create(op.get_bind())
    op.add_column("tenant_admin_invites", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("tenant_admin_invites", sa.Column("purpose", purpose, server_default="BOOTSTRAP", nullable=False))
    op.create_foreign_key("fk_tenant_admin_invites_user_id", "tenant_admin_invites", "tenant_users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_tenant_admin_invites_user_id", "tenant_admin_invites", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_admin_invites_user_id", table_name="tenant_admin_invites")
    op.drop_constraint("fk_tenant_admin_invites_user_id", "tenant_admin_invites", type_="foreignkey")
    op.drop_column("tenant_admin_invites", "purpose")
    op.drop_column("tenant_admin_invites", "user_id")
    postgresql.ENUM(name="tenant_invite_purpose").drop(op.get_bind())
