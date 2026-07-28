"""Repair and backfill tenant SSO provider configuration.

Revision ID: 6e2f4b9c1a77
Revises: 0d6a48f13c2b

The PostgreSQL enum keeps its historical labels on downgrade because PostgreSQL
cannot safely remove enum values in place. Rows are converted back before the
Entra tenant metadata column is removed.
"""

import re
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision = "6e2f4b9c1a77"
down_revision = "0d6a48f13c2b"
branch_labels = None
depends_on = None

ENTRA_ISSUER = re.compile(
    r"^https://login\.microsoftonline\.com/"
    r"(?P<tenant_id>[0-9a-fA-F-]{36})/v2\.0/?$"
)


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_sso_configs")
    }


def _backfill_entra_tenant_ids() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, issuer_url FROM tenant_sso_configs "
            "WHERE entra_tenant_id IS NULL AND issuer_url IS NOT NULL"
        )
    )
    for row in rows:
        match = ENTRA_ISSUER.fullmatch(row.issuer_url)
        if match is None:
            continue
        try:
            tenant_id = str(UUID(match.group("tenant_id")))
        except ValueError:
            continue
        connection.execute(
            sa.text(
                "UPDATE tenant_sso_configs SET entra_tenant_id = :tenant_id "
                "WHERE id = :config_id AND entra_tenant_id IS NULL"
            ),
            {"tenant_id": tenant_id, "config_id": row.id},
        )


def upgrade() -> None:
    if "entra_tenant_id" not in _columns():
        op.add_column(
            "tenant_sso_configs",
            sa.Column("entra_tenant_id", sa.String(length=255), nullable=True),
        )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE sso_provider ADD VALUE IF NOT EXISTS "
                "'MICROSOFT_ENTRA'"
            )
    op.execute(
        "UPDATE tenant_sso_configs SET provider = 'MICROSOFT_ENTRA' "
        "WHERE provider = 'ENTRA_ID'"
    )
    op.execute(
        "UPDATE tenant_sso_configs SET provider = 'GENERIC_OIDC' "
        "WHERE provider = 'OKTA'"
    )
    op.alter_column(
        "tenant_sso_configs",
        "client_secret_encrypted",
        existing_type=sa.String(length=1000),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )
    _backfill_entra_tenant_ids()


def downgrade() -> None:
    op.execute(
        "UPDATE tenant_sso_configs SET provider = 'ENTRA_ID' "
        "WHERE provider = 'MICROSOFT_ENTRA'"
    )
    op.alter_column(
        "tenant_sso_configs",
        "client_secret_encrypted",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=1000),
        existing_nullable=True,
    )
    if "entra_tenant_id" in _columns():
        op.drop_column("tenant_sso_configs", "entra_tenant_id")
