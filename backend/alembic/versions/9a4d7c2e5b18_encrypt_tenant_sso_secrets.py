"""Encrypt legacy tenant SSO client secrets at rest.

Revision ID: 9a4d7c2e5b18
Revises: 6e2f4b9c1a77

Downgrade intentionally leaves ciphertext in place. Automatically restoring
plaintext would weaken the at-rest security guarantee. A simultaneous rollback
to application code without the compatibility cipher requires administrators
to replace affected client secrets.
"""

from alembic import op
import sqlalchemy as sa

from app.services.oidc_secret_cipher import OIDCSecretCipher


revision = "9a4d7c2e5b18"
down_revision = "6e2f4b9c1a77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    cipher = OIDCSecretCipher()
    rows = connection.execute(
        sa.text(
            "SELECT id, client_secret_encrypted FROM tenant_sso_configs "
            "WHERE client_secret_encrypted IS NOT NULL"
        )
    )
    for row in rows:
        if cipher.is_encrypted(row.client_secret_encrypted):
            continue
        connection.execute(
            sa.text(
                "UPDATE tenant_sso_configs "
                "SET client_secret_encrypted = :encrypted_secret "
                "WHERE id = :config_id"
            ),
            {
                "encrypted_secret": cipher.encrypt(row.client_secret_encrypted),
                "config_id": row.id,
            },
        )


def downgrade() -> None:
    # Intentionally do not write plaintext secrets back to PostgreSQL.
    pass
