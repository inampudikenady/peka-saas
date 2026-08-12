from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.ai_conversation import (
    AIConversationMessage,
    AIMessageStatus,
)
from app.repositories.ai_conversation_repository import AIConversationRepository
from app.services.ai_conversation_service import (
    AIConversationService,
    ConversationGenerationInProgressError,
    ConversationNotFoundError,
    deterministic_title,
    normalize_conversation_preview,
    redact_content,
)


def service():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    return AIConversationService(AIConversationRepository(db)), db


def test_owner_can_create_complete_and_retrieve_conversation():
    value, _db = service()
    tenant_id, user_id = uuid4(), uuid4()
    conversation, assistant = value.begin_message(
        tenant_id, user_id, "How do I install vManager?"
    )
    value.complete(
        tenant_id, user_id, assistant.id,
        content="### Installation\n\n- Install it. [C1]",
        citations=[{
            "citation_id": "C1", "source_type": "document",
            "document_id": str(uuid4()), "version_id": str(uuid4()),
            "chunk_id": str(uuid4()), "title": "Guide", "page_number": 2,
            "section_title": "Install", "sheet_name": None,
            "row_start": None, "row_end": None, "score": 0.9,
        }],
        retrieval={"result_count": 1, "included_count": 1, "top_k": 8},
        model="qwen3:8b", prompt_version="ai-answer-v1",
    )
    detail = value.detail(tenant_id, user_id, conversation.id)
    assert detail.title == "Installing vManager"
    assert [message.role.value for message in detail.messages] == ["user", "assistant"]
    assert detail.messages[1].status == AIMessageStatus.COMPLETED
    assert detail.messages[1].content == "### Installation\n\n- Install it. [C1]"
    assert detail.messages[1].citations[0].title == "Guide"
    assert detail.messages[1].prompt_version == "ai-answer-v1"
    summary = value.list(
        tenant_id, user_id, limit=30, offset=0, archived=False
    ).items[0]
    assert summary.last_message_preview == "Installation Install it."
    snapshot = value.citation_evidence(
        tenant_id, user_id, conversation.id, assistant.id, "C1"
    )
    assert snapshot.citation.title == "Guide"
    with pytest.raises(ConversationNotFoundError):
        value.citation_evidence(
            tenant_id, uuid4(), conversation.id, assistant.id, "C1"
        )
    with pytest.raises(ConversationNotFoundError):
        value.citation_evidence(
            tenant_id, user_id, conversation.id, assistant.id, "C99"
        )


def test_same_tenant_other_user_admin_and_other_tenant_get_not_found():
    value, _db = service()
    tenant_id, owner_id = uuid4(), uuid4()
    conversation, _assistant = value.begin_message(
        tenant_id, owner_id, "Private question"
    )
    for other_tenant, other_user in (
        (tenant_id, uuid4()),  # same-tenant user or tenant admin
        (uuid4(), owner_id),  # same user identity cannot cross tenant
        (uuid4(), uuid4()),
    ):
        with pytest.raises(ConversationNotFoundError):
            value.detail(other_tenant, other_user, conversation.id)
        with pytest.raises(ConversationNotFoundError):
            value.rename(other_tenant, other_user, conversation.id, "Stolen")
        with pytest.raises(ConversationNotFoundError):
            value.archive(other_tenant, other_user, conversation.id, True)
        with pytest.raises(ConversationNotFoundError):
            value.delete(other_tenant, other_user, conversation.id)


def test_listing_is_owner_scoped_paginated_and_ordered():
    value, _db = service()
    tenant_id, user_id = uuid4(), uuid4()
    first, _ = value.begin_message(tenant_id, user_id, "First")
    second, _ = value.begin_message(tenant_id, user_id, "Second")
    value.begin_message(tenant_id, uuid4(), "Other user's chat")
    value.begin_message(uuid4(), user_id, "Other tenant chat")
    first.last_message_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    value.repository.commit()
    page = value.list(
        tenant_id, user_id, limit=1, offset=0, archived=False
    )
    assert page.total == 2
    assert [item.id for item in page.items] == [first.id]
    page_two = value.list(
        tenant_id, user_id, limit=1, offset=1, archived=False
    )
    assert [item.id for item in page_two.items] == [second.id]


def test_rename_archive_delete_and_cancel_are_owner_only():
    value, _db = service()
    tenant_id, user_id = uuid4(), uuid4()
    conversation, assistant = value.begin_message(tenant_id, user_id, "Question")
    assert value.rename(
        tenant_id, user_id, conversation.id, "Renamed"
    ).title == "Renamed"
    assert value.archive(
        tenant_id, user_id, conversation.id, True
    ).is_archived is True
    assert value.list(
        tenant_id, user_id, limit=30, offset=0, archived=False
    ).total == 0
    assert value.list(
        tenant_id, user_id, limit=30, offset=0, archived=True
    ).items[0].id == conversation.id
    value.terminate(
        tenant_id, user_id, assistant.id,
        status=AIMessageStatus.CANCELLED,
        partial_content="Partial", code="CLIENT_DISCONNECTED",
    )
    detail = value.detail(tenant_id, user_id, conversation.id)
    assert detail.messages[-1].status == AIMessageStatus.CANCELLED
    assert detail.messages[-1].content == "Partial"
    value.delete(tenant_id, user_id, conversation.id)
    with pytest.raises(ConversationNotFoundError):
        value.detail(tenant_id, user_id, conversation.id)


def test_second_generation_in_same_conversation_is_rejected():
    value, _db = service()
    tenant_id, user_id = uuid4(), uuid4()
    conversation, _assistant = value.begin_message(
        tenant_id, user_id, "First question"
    )
    with pytest.raises(ConversationGenerationInProgressError):
        value.begin_message(
            tenant_id, user_id, "Overlapping question", conversation.id
        )


def test_stale_streaming_messages_are_failed_and_secrets_are_redacted():
    value, db = service()
    tenant_id, user_id = uuid4(), uuid4()
    _conversation, assistant = value.begin_message(
        tenant_id, user_id, "password=hunter2 explain setup"
    )
    assistant.created_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    db.commit()
    value.list(tenant_id, user_id, limit=30, offset=0, archived=False)
    stored = db.scalar(select(AIConversationMessage).where(
        AIConversationMessage.id == assistant.id
    ))
    assert stored.status == AIMessageStatus.FAILED
    assert redact_content("api_key=private") == "[REDACTED SECRET]"
    messages = value.repository.messages(
        tenant_id, user_id, assistant.conversation_id
    )
    assert "hunter2" not in messages[0].content


def test_titles_are_clean_and_citation_storage_redacts_defensively():
    value, _db = service()
    tenant_id, user_id = uuid4(), uuid4()
    assert deterministic_title(
        "Summarize the Ventana runbook."
    ) == "Ventana Runbook Summary"
    conversation, assistant = value.begin_message(
        tenant_id, user_id, "Summarize the Ventana runbook."
    )
    value.complete(
        tenant_id, user_id, assistant.id,
        content="Use the approved credential store.",
        citations=[{
            "citation_id": "C1", "source_type": "document",
            "document_id": str(uuid4()), "version_id": str(uuid4()),
            "chunk_id": str(uuid4()), "title": "Password: hunter2",
            "excerpt": "api_key=private-value", "page_number": None,
            "section_title": None, "sheet_name": None,
            "row_start": None, "row_end": None, "score": 0.9,
        }],
        retrieval={}, model="test", prompt_version="v1",
    )
    stored = value.detail(tenant_id, user_id, conversation.id).messages[-1].citations[0]
    assert "hunter2" not in stored.title
    assert "private-value" not in (stored.excerpt or "")
    assert stored.sensitive_content_redacted is True


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("### Roche Infrastructure Details\n\nAvailable systems.", "Roche Infrastructure Details Available systems."),
        ("- **Login node:** `ln1` [C1]\n- Bastion host", "Login node: ln1 Bastion host"),
        ("```bash\npeka verify --host ln1\n```", "peka verify --host ln1"),
        ("> Review the [runbook](https://example.test). [C2]", "Review the runbook."),
        ("Ordinary plain text.", "Ordinary plain text."),
        ("  \n###\n```text\n```", None),
    ],
)
def test_conversation_preview_normalizes_markdown_without_rewriting(content, expected):
    assert normalize_conversation_preview(content) == expected


def test_conversation_preview_adds_ellipsis_only_when_truncated():
    assert normalize_conversation_preview("Short answer.", limit=20) == "Short answer."
    assert normalize_conversation_preview(
        "This answer contains more words than the preview allows.",
        limit=28,
    ) == "This answer contains more…"


def test_continuation_context_is_owned_and_drops_old_citation_labels():
    value, _db = service()
    tenant_id, user_id = uuid4(), uuid4()
    conversation, assistant = value.begin_message(
        tenant_id, user_id, "How do I install it?"
    )
    value.complete(
        tenant_id, user_id, assistant.id,
        content="Use the signed package. [C1]", citations=[],
        retrieval={
            "operational_context": {
                "tool_name": "count_assets",
                "arguments": {"os_family": "linux"},
            }
        },
        model="test", prompt_version="v1",
    )
    context = value.generation_context(tenant_id, user_id, conversation.id)
    assert "How do I install it?" in context.text
    assert "Use the signed package." in context.text
    assert "[C1]" not in context.text
    assert context.message_ids
    assert context.operational_context == {
        "tool_name": "count_assets",
        "arguments": {"os_family": "linux"},
    }
    _conversation, followup = value.begin_message(
        tenant_id, user_id, "What about Windows?", conversation.id,
        context_message_ids=context.message_ids,
    )
    detail = value.detail(tenant_id, user_id, conversation.id)
    assert detail.messages[-1].id == followup.id
    assert detail.messages[-1].context_message_ids == context.message_ids
    with pytest.raises(ConversationNotFoundError):
        value.generation_context(tenant_id, uuid4(), conversation.id)


def test_context_limits_prefer_recent_messages_predictably():
    value, _db = service()
    value.config = value.config.model_copy(update={
        "peka_ai_max_prior_messages": 2,
        "peka_ai_max_history_tokens": 1200,
    })
    tenant_id, user_id = uuid4(), uuid4()
    conversation, first = value.begin_message(
        tenant_id, user_id, "Old question"
    )
    value.complete(
        tenant_id, user_id, first.id, content="Old answer",
        citations=[], retrieval={}, model="test", prompt_version="v1",
    )
    _conversation, second = value.begin_message(
        tenant_id, user_id, "Recent question", conversation.id
    )
    value.complete(
        tenant_id, user_id, second.id, content="Recent answer",
        citations=[], retrieval={}, model="test", prompt_version="v1",
    )
    context = value.generation_context(tenant_id, user_id, conversation.id)
    assert context.text == "USER: Recent question\nASSISTANT: Recent answer"
    assert len(context.message_ids) == 2

    value.config = value.config.model_copy(update={
        "peka_ai_max_history_tokens": 0,
    })
    empty = value.generation_context(tenant_id, user_id, conversation.id)
    assert empty.text == ""
    assert empty.message_ids == []


def test_platform_routes_do_not_reference_conversation_content():
    from pathlib import Path

    platform_routes = Path("app/api/routes/platform")
    source = "\n".join(
        path.read_text() for path in platform_routes.glob("*.py")
    ).lower()
    assert "ai_conversation" not in source
    assert "conversation_message" not in source
