"""Add AI conversation search and active-generation indexes.

Revision ID: c53f9a7b2e41
Revises: c42e8b6a1d30
"""

from alembic import op


revision = "c53f9a7b2e41"
down_revision = "c42e8b6a1d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_conversations_owner_title",
        "ai_conversations",
        ["tenant_id", "user_id", "title"],
    )
    op.create_index(
        "uq_ai_conversation_active_generation",
        "ai_conversation_messages",
        ["conversation_id"],
        unique=True,
        postgresql_where=(
            "status = 'STREAMING' AND role = 'ASSISTANT'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ai_conversation_active_generation",
        table_name="ai_conversation_messages",
    )
    op.drop_index(
        "ix_ai_conversations_owner_title",
        table_name="ai_conversations",
    )
