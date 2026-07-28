"""Typed stateless grounded-answer API contracts."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document_api import SearchFilters


class AIAnswerErrorCode(str, Enum):
    INVALID_QUERY = "INVALID_QUERY"
    QUERY_TOO_LONG = "QUERY_TOO_LONG"
    INVALID_FILTER = "INVALID_FILTER"
    KNOWLEDGE_UNAVAILABLE = "KNOWLEDGE_UNAVAILABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CHAT_PROVIDER_NOT_CONFIGURED = "CHAT_PROVIDER_NOT_CONFIGURED"
    CHAT_PROVIDER_UNAVAILABLE = "CHAT_PROVIDER_UNAVAILABLE"
    CHAT_PROVIDER_TIMEOUT = "CHAT_PROVIDER_TIMEOUT"
    CHAT_PROVIDER_RATE_LIMITED = "CHAT_PROVIDER_RATE_LIMITED"
    CHAT_PROVIDER_INVALID_RESPONSE = "CHAT_PROVIDER_INVALID_RESPONSE"
    CONTEXT_LIMIT_EXCEEDED = "CONTEXT_LIMIT_EXCEEDED"
    CITATION_VALIDATION_FAILED = "CITATION_VALIDATION_FAILED"
    AI_GENERATION_FAILED = "AI_GENERATION_FAILED"


class AIAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    conversation_id: UUID | None = None

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class AIAnswerCitation(BaseModel):
    citation_id: str
    source_type: str
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    title: str
    page_number: int | None = None
    section_title: str | None = None
    sheet_name: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    score: float
    excerpt: str | None = None
    document_type: str | None = None
    source_system: str | None = None
    source_id: str | None = None
    ingested_at: str | None = None
    revision: str | None = None
    sensitive_content_redacted: bool = False
    redaction_categories: list[str] = Field(default_factory=list)


class AIRetrievalSummary(BaseModel):
    result_count: int
    included_count: int
    top_k: int


class AIModelSummary(BaseModel):
    provider: str
    model: str


class AIAnswerResponse(BaseModel):
    answer: str
    grounded: bool
    code: AIAnswerErrorCode | None = None
    citations: list[AIAnswerCitation] = Field(default_factory=list)
    retrieval: AIRetrievalSummary
    model: AIModelSummary | None = None
    request_id: str


class AIAnswerErrorResponse(BaseModel):
    code: AIAnswerErrorCode
    message: str
    request_id: str


class AIPromptSuggestionsResponse(BaseModel):
    has_indexed_knowledge: bool
    suggestions: list[str] = Field(default_factory=list)
    onboarding_guidance: str | None = None
