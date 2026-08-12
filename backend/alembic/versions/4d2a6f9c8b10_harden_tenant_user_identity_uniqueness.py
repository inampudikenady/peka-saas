"""Harden tenant-scoped identity uniqueness.

Revision ID: 4d2a6f9c8b10
Revises: c7e4a91d2b60
"""

from alembic import op


revision = "4d2a6f9c8b10"
down_revision = "c7e4a91d2b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Refuse to guess which identity is authoritative. Operators must resolve
    # duplicates explicitly before this migration can continue.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM tenant_users
                GROUP BY tenant_id, lower(btrim(email))
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot enforce tenant user email uniqueness: duplicate normalized emails exist';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM tenant_users
                WHERE external_subject IS NOT NULL
                GROUP BY tenant_id, external_subject
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot enforce tenant user subject uniqueness: duplicate external subjects exist';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_tenant_users_tenant_normalized_email
        ON tenant_users (tenant_id, lower(btrim(email)))
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_tenant_users_tenant_external_subject
        ON tenant_users (tenant_id, external_subject)
        WHERE external_subject IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tenant_users_tenant_external_subject",
        table_name="tenant_users",
    )
    op.drop_index(
        "uq_tenant_users_tenant_normalized_email",
        table_name="tenant_users",
    )
