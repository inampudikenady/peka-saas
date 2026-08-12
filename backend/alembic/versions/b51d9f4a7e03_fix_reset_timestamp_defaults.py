"""Fix timestamp defaults for password reset records.

Revision ID: b51d9f4a7e03
Revises: a41c8e3f6d92
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b51d9f4a7e03"
down_revision: Union[str, Sequence[str], None] = "a41c8e3f6d92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("tenant_password_reset_tokens", "development_emails"):
        for column_name in ("created_at", "updated_at"):
            op.alter_column(
                table_name,
                column_name,
                server_default=sa.func.now(),
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
            )


def downgrade() -> None:
    for table_name in ("tenant_password_reset_tokens", "development_emails"):
        for column_name in ("created_at", "updated_at"):
            op.alter_column(
                table_name,
                column_name,
                server_default=None,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
            )
