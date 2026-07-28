"""Add private tenant-user AI conversations and messages.

Revision ID: c31a7f4d9b20
Revises: b24d9e6f1a32
"""

from alembic import op
import sqlalchemy as sa


revision = "c31a7f4d9b20"
down_revision = "b24d9e6f1a32"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    ]


def upgrade() -> None:
    role = sa.Enum("USER", "ASSISTANT", name="ai_message_role")
    status = sa.Enum(
        "STREAMING", "COMPLETED", "FAILED", "CANCELLED",
        name="ai_message_status",
    )
    op.create_table(
        "ai_conversations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_archived", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["tenant_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_conversations_tenant_id", "ai_conversations", ["tenant_id"]
    )
    op.create_index(
        "ix_ai_conversations_user_id", "ai_conversations", ["user_id"]
    )
    op.create_index(
        "ix_ai_conversations_owner_last_message",
        "ai_conversations", ["tenant_id", "user_id", "last_message_at"],
    )
    op.create_index(
        "ix_ai_conversations_owner_visibility",
        "ai_conversations",
        ["tenant_id", "user_id", "deleted_at", "is_archived"],
    )

    op.create_table(
        "ai_conversation_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column(
            "citations", sa.JSON(), server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "retrieval_metadata", sa.JSON(),
            server_default=sa.text("'{}'::json"), nullable=False,
        ),
        sa.Column(
            "failure_metadata", sa.JSON(),
            server_default=sa.text("'{}'::json"), nullable=False,
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["tenant_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_conversation_messages_conversation_id",
        "ai_conversation_messages", ["conversation_id"],
    )
    op.create_index(
        "ix_ai_conversation_messages_tenant_id",
        "ai_conversation_messages", ["tenant_id"],
    )
    op.create_index(
        "ix_ai_conversation_messages_user_id",
        "ai_conversation_messages", ["user_id"],
    )
    op.create_index(
        "ix_ai_conversation_messages_conversation_created",
        "ai_conversation_messages", ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_ai_conversation_messages_owner",
        "ai_conversation_messages",
        ["tenant_id", "user_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_table("ai_conversation_messages")
    op.drop_table("ai_conversations")
    sa.Enum(name="ai_message_status").drop(op.get_bind())
    sa.Enum(name="ai_message_role").drop(op.get_bind())
