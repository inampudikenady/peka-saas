"""Persist AI context message identifiers.

Revision ID: c42e8b6a1d30
Revises: c31a7f4d9b20
"""

from alembic import op
import sqlalchemy as sa


revision = "c42e8b6a1d30"
down_revision = "c31a7f4d9b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_conversation_messages",
        sa.Column(
            "context_message_ids",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_conversation_messages", "context_message_ids")
