"""Owner-scoped AI conversation API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.ai_conversation import AIMessageRole, AIMessageStatus
from app.schemas.ai_answer import AIAnswerCitation


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=160)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class ConversationArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_archived: bool


class ConversationMessageView(BaseModel):
    id: UUID
    role: AIMessageRole
    content: str
    status: AIMessageStatus
    created_at: datetime
    completed_at: datetime | None
    model: str | None
    prompt_version: str | None
    citations: list[AIAnswerCitation] = Field(default_factory=list)
    retrieval_metadata: dict = Field(default_factory=dict)
    failure_metadata: dict = Field(default_factory=dict)
    context_message_ids: list[UUID] = Field(default_factory=list)


class CitationEvidence(BaseModel):
    message_id: UUID
    citation: AIAnswerCitation


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    is_archived: bool
    last_message_preview: str | None = None


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageView]


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int
