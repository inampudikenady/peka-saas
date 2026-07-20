"""Add V1 tenant user roles.

Revision ID: d9e7f1b5a321
Revises: c8d6e9a4f210
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d9e7f1b5a321"
down_revision = "c8d6e9a4f210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = postgresql.ENUM("TENANT_ADMIN", "TENANT_USER", name="tenant_user_role", create_type=False)
    role.create(op.get_bind())
    op.add_column("tenant_users", sa.Column("role", role, server_default="TENANT_USER", nullable=False))
    op.execute("UPDATE tenant_users SET role = 'TENANT_ADMIN' WHERE auth_source = 'LOCAL' AND username LIKE 'admin\\_%' ESCAPE '\\'")


def downgrade() -> None:
    op.drop_column("tenant_users", "role")
    postgresql.ENUM(name="tenant_user_role").drop(op.get_bind())
