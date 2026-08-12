"""Database operations that always require tenant and user ownership."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.ai_conversation import (
    AIConversation,
    AIConversationMessage,
    AIMessageRole,
    AIMessageStatus,
)


class AIConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def add(self, entity):
        self.session.add(entity)
        return entity

    def owned(
        self,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> AIConversation | None:
        query = select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == user_id,
        )
        if not include_deleted:
            query = query.where(AIConversation.deleted_at.is_(None))
        return self.session.scalar(query)

    def list_owned(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        archived: bool | None,
    ) -> tuple[list[AIConversation], int]:
        filters = [
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == user_id,
            AIConversation.deleted_at.is_(None),
        ]
        if archived is not None:
            filters.append(AIConversation.is_archived.is_(archived))
        total = (
            self.session.scalar(
                select(func.count()).select_from(AIConversation).where(*filters)
            )
            or 0
        )
        items = list(
            self.session.scalars(
                select(AIConversation)
                .where(*filters)
                .order_by(
                    AIConversation.last_message_at.desc(), AIConversation.id.desc()
                )
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return items, total

    def messages(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> list[AIConversationMessage]:
        return list(
            self.session.scalars(
                select(AIConversationMessage)
                .where(
                    AIConversationMessage.tenant_id == tenant_id,
                    AIConversationMessage.user_id == user_id,
                    AIConversationMessage.conversation_id == conversation_id,
                )
                .order_by(AIConversationMessage.created_at, AIConversationMessage.id)
            ).all()
        )

    def last_preview(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> str | None:
        return self.session.scalar(
            select(AIConversationMessage.content)
            .where(
                AIConversationMessage.tenant_id == tenant_id,
                AIConversationMessage.user_id == user_id,
                AIConversationMessage.conversation_id == conversation_id,
            )
            .order_by(
                AIConversationMessage.created_at.desc(),
                AIConversationMessage.id.desc(),
            )
            .limit(1)
        )

    def fail_stale(self, tenant_id: UUID, user_id: UUID) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        result = self.session.execute(
            update(AIConversationMessage)
            .where(
                AIConversationMessage.tenant_id == tenant_id,
                AIConversationMessage.user_id == user_id,
                AIConversationMessage.status == AIMessageStatus.STREAMING,
                AIConversationMessage.created_at < cutoff,
            )
            .values(
                status=AIMessageStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                failure_metadata={"code": "INTERRUPTED"},
            ),
            execution_options={"synchronize_session": False},
        )
        count = int(result.rowcount or 0)
        if count:
            self.session.expire_all()
        return count

    def has_active_generation(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> bool:
        return (
            self.session.scalar(
                select(AIConversationMessage.id)
                .where(
                    AIConversationMessage.tenant_id == tenant_id,
                    AIConversationMessage.user_id == user_id,
                    AIConversationMessage.conversation_id == conversation_id,
                    AIConversationMessage.role == AIMessageRole.ASSISTANT,
                    AIConversationMessage.status == AIMessageStatus.STREAMING,
                )
                .limit(1)
            )
            is not None
        )

    def create_pair(
        self,
        conversation: AIConversation,
        user_message: AIConversationMessage,
        assistant_message: AIConversationMessage,
    ) -> None:
        self.add(conversation)
        self.session.flush()
        user_message.conversation_id = conversation.id
        assistant_message.conversation_id = conversation.id
        self.add(user_message)
        self.add(assistant_message)
        self.commit()

    def message_owned(
        self, tenant_id: UUID, user_id: UUID, message_id: UUID
    ) -> AIConversationMessage | None:
        return self.session.scalar(
            select(AIConversationMessage).where(
                AIConversationMessage.id == message_id,
                AIConversationMessage.tenant_id == tenant_id,
                AIConversationMessage.user_id == user_id,
            )
        )
