"""Store Microsoft Entra tenant and derived metadata URL.

Revision ID: 0d6a48f13c2b
Revises: c53f9a7b2e41
"""

from alembic import op
import sqlalchemy as sa


revision = "0d6a48f13c2b"
down_revision = "c53f9a7b2e41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_sso_configs")
    }
    if "entra_tenant_id" not in columns:
        op.add_column(
            "tenant_sso_configs",
            sa.Column("entra_tenant_id", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_sso_configs")
    }
    if "metadata_url" in columns:
        op.drop_column("tenant_sso_configs", "metadata_url")
    if "entra_tenant_id" in columns:
        op.drop_column("tenant_sso_configs", "entra_tenant_id")
