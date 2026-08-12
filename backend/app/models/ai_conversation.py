"""Private tenant-user AI conversation persistence."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class AIMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class AIMessageStatus(str, enum.Enum):
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AIConversation(Entity):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index(
            "ix_ai_conversations_owner_last_message",
            "tenant_id",
            "user_id",
            "last_message_at",
        ),
        Index(
            "ix_ai_conversations_owner_visibility",
            "tenant_id",
            "user_id",
            "deleted_at",
            "is_archived",
        ),
        Index(
            "ix_ai_conversations_owner_title",
            "tenant_id",
            "user_id",
            "title",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIConversationMessage(Entity):
    __tablename__ = "ai_conversation_messages"
    __table_args__ = (
        Index(
            "ix_ai_conversation_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index(
            "ix_ai_conversation_messages_owner",
            "tenant_id",
            "user_id",
            "conversation_id",
        ),
        Index(
            "uq_ai_conversation_active_generation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'STREAMING' AND role = 'ASSISTANT'"),
            sqlite_where=text("status = 'STREAMING' AND role = 'ASSISTANT'"),
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[AIMessageRole] = mapped_column(
        Enum(AIMessageRole, name="ai_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[AIMessageStatus] = mapped_column(
        Enum(AIMessageStatus, name="ai_message_status"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    retrieval_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
