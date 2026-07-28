"""Remove the unused tenant SSO metadata URL cache column.

Revision ID: b7c3e1d8f642
Revises: 9a4d7c2e5b18
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c3e1d8f642"
down_revision = "9a4d7c2e5b18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_sso_configs")
    }
    if "metadata_url" in columns:
        op.drop_column("tenant_sso_configs", "metadata_url")


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_sso_configs")
    }
    if "metadata_url" not in columns:
        op.add_column(
            "tenant_sso_configs",
            sa.Column("metadata_url", sa.String(length=500), nullable=True),
        )
