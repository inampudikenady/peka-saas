"""Private conversation lifecycle and safe answer persistence."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, settings
from app.models.ai_conversation import (
    AIConversation,
    AIConversationMessage,
    AIMessageRole,
    AIMessageStatus,
)
from app.repositories.ai_conversation_repository import AIConversationRepository
from app.schemas.ai_conversation import (
    ConversationDetail,
    ConversationList,
    ConversationMessageView,
    ConversationSummary,
    CitationEvidence,
)
from app.schemas.ai_answer import AIAnswerCitation
from app.services.prompt_builder import estimate_tokens
from app.services.secret_redaction import SecretRedactionService


class ConversationNotFoundError(LookupError):
    pass


class ConversationGenerationInProgressError(RuntimeError):
    pass


def redact_content(value: str) -> str:
    """Compatibility helper backed by the centralized production redactor."""
    return SecretRedactionService().redact(value).text


def normalize_conversation_preview(
    value: str | None,
    *,
    limit: int = 120,
) -> str | None:
    """Build a readable summary without changing the stored message."""
    if not value or not value.strip() or limit <= 0:
        return None

    normalized = re.sub(r"```[^\n]*\n?", "", value)
    normalized = normalized.replace("```", "")
    normalized = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"\[C[1-9]\d*\]", "", normalized)
    normalized = re.sub(r"`([^`]*)`", r"\1", normalized)
    normalized = re.sub(r"(\*\*|__)(.*?)\1", r"\2", normalized)
    normalized = re.sub(r"(?<!\w)([*_~])([^*_\n~]+)\1(?!\w)", r"\2", normalized)

    meaningful_lines: list[str] = []
    for line in normalized.splitlines():
        line = re.sub(
            r"^\s{0,3}(?:#{1,6}\s*|>\s*|[-+*]\s+|\d+[.)]\s+)",
            "",
            line,
        )
        line = " ".join(line.split()).strip(" \t-–—:;|")
        if line:
            meaningful_lines.append(line)

    preview = " ".join(meaningful_lines)
    if not preview:
        return None
    if len(preview) <= limit:
        return preview

    shortened = preview[: max(1, limit - 1)].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    shortened = shortened.rstrip(" \t-–—:;|")
    return f"{shortened}…"


@dataclass(frozen=True)
class ConversationContext:
    text: str
    message_ids: list[UUID]


def deterministic_title(question: str, redactor: SecretRedactionService | None = None) -> str:
    safe = (redactor or SecretRedactionService()).redact(question).text
    title = " ".join(safe.split()).strip(" .?!")
    install = re.match(r"(?i)^how (?:do|can) i install\s+(.+)$", title)
    if install:
        title = f"Installing {install.group(1)}"
    summary = re.match(r"(?i)^summarize (?:the )?(.+?)(?: runbook)?$", title)
    if summary:
        subject = summary.group(1)
        if "runbook" not in subject.casefold():
            subject += " Runbook"
        title = f"{subject} Summary"
    if len(title) <= 72:
        return title
    return title[:69].rstrip() + "…"


class AIConversationService:
    def __init__(
        self,
        repository: AIConversationRepository,
        config: Settings = settings,
    ) -> None:
        self.repository = repository
        self.config = config
        self.redactor = SecretRedactionService(
            enabled=config.peka_ai_secret_detection_enabled
        )

    def _owned(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> AIConversation:
        conversation = self.repository.owned(tenant_id, user_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError
        return conversation

    def create(self, tenant_id: UUID, user_id: UUID, title: str | None = None):
        now = datetime.now(timezone.utc)
        conversation = AIConversation(
            tenant_id=tenant_id,
            user_id=user_id,
            title=self.redactor.redact((title or "New chat").strip()).text or "New chat",
            last_message_at=now,
        )
        self.repository.add(conversation)
        self.repository.commit()
        return self.detail(tenant_id, user_id, conversation.id)

    def begin_message(
        self, tenant_id: UUID, user_id: UUID, question: str,
        conversation_id: UUID | None = None,
        context_message_ids: list[UUID] | None = None,
    ) -> tuple[AIConversation, AIConversationMessage]:
        self.repository.fail_stale(tenant_id, user_id)
        now = datetime.now(timezone.utc)
        safe_question = self.redactor.redact(question).text
        if conversation_id is None:
            conversation = AIConversation(
                tenant_id=tenant_id,
                user_id=user_id,
                title=deterministic_title(question, self.redactor),
                last_message_at=now,
            )
        else:
            conversation = self._owned(tenant_id, user_id, conversation_id)
            if self.repository.has_active_generation(
                tenant_id, user_id, conversation.id
            ):
                raise ConversationGenerationInProgressError
            if not self.repository.messages(tenant_id, user_id, conversation.id):
                conversation.title = deterministic_title(question, self.redactor)
            conversation.last_message_at = now
            conversation.is_archived = False
        user_message = AIConversationMessage(
            conversation_id=conversation.id,
            tenant_id=tenant_id, user_id=user_id, role=AIMessageRole.USER,
            content=safe_question, status=AIMessageStatus.COMPLETED,
            completed_at=now, created_at=now,
        )
        assistant = AIConversationMessage(
            conversation_id=conversation.id,
            tenant_id=tenant_id, user_id=user_id, role=AIMessageRole.ASSISTANT,
            content="", status=AIMessageStatus.STREAMING,
            created_at=now + timedelta(microseconds=1),
            context_message_ids=[
                str(message_id) for message_id in (context_message_ids or [])
            ],
        )
        if conversation_id is None:
            self.repository.create_pair(conversation, user_message, assistant)
        else:
            self.repository.add(user_message)
            self.repository.add(assistant)
            try:
                self.repository.commit()
            except IntegrityError as exc:
                self.repository.rollback()
                raise ConversationGenerationInProgressError from exc
        return conversation, assistant

    def generation_context(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> ConversationContext:
        conversation = self._owned(tenant_id, user_id, conversation_id)
        messages = [
            message
            for message in self.repository.messages(
                tenant_id, user_id, conversation.id
            )
            if message.status == AIMessageStatus.COMPLETED and message.content
        ]
        selected: list[tuple[AIConversationMessage, str]] = []
        used_tokens = 0
        for message in reversed(messages):
            # Citation labels from prior turns are not valid identifiers for the
            # newly retrieved evidence used by this answer.
            content = re.sub(r"\[C\d+\]", "", message.content)
            content = " ".join(content.split())[:1000]
            line = f"{message.role.value.upper()}: {content}"
            tokens = estimate_tokens(line)
            if (
                len(selected) >= self.config.peka_ai_max_prior_messages
                or used_tokens + tokens > self.config.peka_ai_max_history_tokens
            ):
                break
            selected.append((message, line))
            used_tokens += tokens
        selected.reverse()
        return ConversationContext(
            text="\n".join(line for _message, line in selected),
            message_ids=[message.id for message, _line in selected],
        )

    def complete(
        self, tenant_id: UUID, user_id: UUID, message_id: UUID, *,
        content: str, citations: list[dict], retrieval: dict,
        model: str | None, prompt_version: str | None,
    ) -> None:
        message = self.repository.message_owned(tenant_id, user_id, message_id)
        if message is None:
            raise ConversationNotFoundError
        message.content = self.redactor.redact(content).text
        safe_citations: list[dict] = []
        for citation in citations:
            safe_citation = dict(citation)
            categories = set(safe_citation.get("redaction_categories") or [])
            redacted = bool(safe_citation.get("sensitive_content_redacted"))
            for field in (
                "excerpt", "title", "section_title", "sheet_name",
                "source_system", "document_type",
            ):
                value = safe_citation.get(field)
                if not isinstance(value, str):
                    continue
                result = self.redactor.redact(value)
                safe_citation[field] = result.text
                if result.detections:
                    redacted = True
                    categories.update(result.detections)
            safe_citation["sensitive_content_redacted"] = redacted
            safe_citation["redaction_categories"] = sorted(categories)
            safe_citations.append(safe_citation)
        message.citations = safe_citations
        message.retrieval_metadata = retrieval
        message.model = model
        message.prompt_version = prompt_version
        message.status = AIMessageStatus.COMPLETED
        message.completed_at = datetime.now(timezone.utc)
        self.repository.commit()

    def terminate(
        self, tenant_id: UUID, user_id: UUID, message_id: UUID, *,
        status: AIMessageStatus, partial_content: str, code: str,
    ) -> None:
        message = self.repository.message_owned(tenant_id, user_id, message_id)
        if message is None or message.status != AIMessageStatus.STREAMING:
            return
        message.content = self.redactor.redact(partial_content).text
        message.status = status
        message.completed_at = datetime.now(timezone.utc)
        message.failure_metadata = {"code": code}
        self.repository.commit()

    def list(
        self, tenant_id: UUID, user_id: UUID, *, limit: int, offset: int,
        archived: bool | None,
    ) -> ConversationList:
        if self.repository.fail_stale(tenant_id, user_id):
            self.repository.commit()
        items, total = self.repository.list_owned(
            tenant_id, user_id, limit=limit, offset=offset, archived=archived
        )
        return ConversationList(
            items=[self._summary(tenant_id, user_id, item) for item in items],
            total=total, limit=limit, offset=offset,
        )

    def detail(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> ConversationDetail:
        conversation = self._owned(tenant_id, user_id, conversation_id)
        summary = self._summary(tenant_id, user_id, conversation)
        messages = self.repository.messages(tenant_id, user_id, conversation.id)
        return ConversationDetail(
            **summary.model_dump(),
            messages=[ConversationMessageView.model_validate(
                {
                    "id": message.id, "role": message.role,
                    "content": message.content, "status": message.status,
                    "created_at": message.created_at,
                    "completed_at": message.completed_at, "model": message.model,
                    "prompt_version": message.prompt_version,
                    "citations": message.citations or [],
                    "retrieval_metadata": message.retrieval_metadata or {},
                    "failure_metadata": message.failure_metadata or {},
                    "context_message_ids": message.context_message_ids or [],
                }
            ) for message in messages],
        )

    def rename(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID, title: str
    ) -> ConversationDetail:
        conversation = self._owned(tenant_id, user_id, conversation_id)
        conversation.title = self.redactor.redact(title).text
        self.repository.commit()
        return self.detail(tenant_id, user_id, conversation_id)

    def archive(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID, value: bool
    ) -> ConversationDetail:
        conversation = self._owned(tenant_id, user_id, conversation_id)
        conversation.is_archived = value
        self.repository.commit()
        return self.detail(tenant_id, user_id, conversation_id)

    def delete(self, tenant_id: UUID, user_id: UUID, conversation_id: UUID) -> None:
        conversation = self._owned(tenant_id, user_id, conversation_id)
        conversation.deleted_at = datetime.now(timezone.utc)
        self.repository.commit()

    def citation_evidence(
        self,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        citation_id: str,
    ) -> CitationEvidence:
        self._owned(tenant_id, user_id, conversation_id)
        message = self.repository.message_owned(tenant_id, user_id, message_id)
        if (
            message is None
            or message.conversation_id != conversation_id
            or message.role != AIMessageRole.ASSISTANT
        ):
            raise ConversationNotFoundError
        for value in message.citations or []:
            if value.get("citation_id") == citation_id:
                return CitationEvidence(
                    message_id=message.id,
                    citation=AIAnswerCitation.model_validate(value),
                )
        raise ConversationNotFoundError

    def _summary(
        self, tenant_id: UUID, user_id: UUID, conversation: AIConversation
    ) -> ConversationSummary:
        preview = self.repository.last_preview(tenant_id, user_id, conversation.id)
        preview = normalize_conversation_preview(preview)
        return ConversationSummary(
            id=conversation.id, title=conversation.title,
            created_at=conversation.created_at, updated_at=conversation.updated_at,
            last_message_at=conversation.last_message_at,
            is_archived=conversation.is_archived,
            last_message_preview=preview or None,
        )
