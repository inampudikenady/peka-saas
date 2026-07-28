import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.auth import allow_tenant_user
from app.api.dependencies import get_ai_conversation_service
from app.api.routes.tenant.ai_answer import get_ai_answer_service, router
from app.api.tenant_context import get_current_tenant_context
from app.db.session import get_db
from app.schemas.ai_answer import (
    AIAnswerResponse,
    AIRetrievalSummary,
)

MARKDOWN_ANSWER = "## Installation\n\n1. Run `peka install`. [C1]"


class FakeService:
    async def answer(self, tenant_id, user_id, payload, request_id, **kwargs):
        return AIAnswerResponse(
            answer=MARKDOWN_ANSWER,
            grounded=True,
            citations=[],
            retrieval=AIRetrievalSummary(result_count=1, included_count=1, top_k=8),
            model={"provider": "fake", "model": "fake"},
            request_id=request_id,
        )

    async def stream_answer(self, tenant_id, user_id, payload, request_id, **kwargs):
        yield {"event": "retrieval", "data": {"result_count": 1, "included_count": 1, "top_k": 8}}
        yield {"event": "token", "data": {"text": MARKDOWN_ANSWER}}
        yield {"event": "citations", "data": {"citations": []}}
        yield {"event": "complete", "data": {"grounded": True, "request_id": request_id}}


class FakeConversationService:
    def __init__(self):
        self.completed = []
        self.terminated = []

    def begin_message(
        self, tenant_id, user_id, question, conversation_id=None, **kwargs
    ):
        return SimpleNamespace(id=conversation_id or uuid4()), SimpleNamespace(id=uuid4())

    def generation_context(self, tenant_id, user_id, conversation_id):
        return SimpleNamespace(text="", message_ids=[])

    def complete(self, tenant_id, user_id, message_id, **values):
        self.completed.append((tenant_id, user_id, message_id, values))

    def terminate(self, tenant_id, user_id, message_id, **values):
        self.terminated.append((tenant_id, user_id, message_id, values))


def app(authenticated=True, service=None, conversation_service=None):
    value = FastAPI()
    value.include_router(router, prefix="/api/v1")
    context = SimpleNamespace(tenant_id=uuid4())
    value.dependency_overrides[get_current_tenant_context] = lambda: context
    value.dependency_overrides[get_ai_answer_service] = lambda: service or FakeService()
    value.dependency_overrides[get_ai_conversation_service] = (
        lambda: conversation_service or FakeConversationService()
    )
    if authenticated:
        value.dependency_overrides[allow_tenant_user] = lambda: SimpleNamespace(id=uuid4())
    else:
        def reject():
            raise HTTPException(status_code=401, detail="Tenant authentication required.")
        value.dependency_overrides[allow_tenant_user] = reject
    return value


def test_synchronous_answer_api():
    response = TestClient(app()).post(
        "/api/v1/tenant/ai/answer", json={"query": "How do I install vManager?"}
    )
    assert response.status_code == 200
    assert response.json()["grounded"] is True
    assert "tenant_id" not in response.json()


def test_prompt_suggestions_use_only_current_tenant_indexed_titles(monkeypatch):
    seen_tenant_ids = []

    def titles(_repository, tenant_id, limit=4):
        seen_tenant_ids.append(tenant_id)
        return ["Acme_Operations.pdf"]

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.DocumentRepository."
        "list_indexed_document_titles",
        titles,
    )
    value = app()
    value.dependency_overrides[get_db] = lambda: SimpleNamespace()
    response = TestClient(value).get("/api/v1/tenant/ai/suggestions")
    assert response.status_code == 200
    assert response.json() == {
        "has_indexed_knowledge": True,
        "suggestions": ["Summarize Acme Operations."],
        "onboarding_guidance": None,
    }
    assert len(seen_tenant_ids) == 1


def test_streaming_answer_event_sequence_has_no_reasoning_event():
    conversations = FakeConversationService()
    response = TestClient(app(conversation_service=conversations)).post(
        "/api/v1/tenant/ai/answer/stream", json={"query": "How?"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        line.removeprefix("event: ")
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]
    assert events == ["status", "retrieval", "token", "citations", "complete"]
    assert "reasoning" not in response.text.lower()
    assert response.text.startswith(
        'event: status\ndata: {"status":"started","request_id":'
    )
    assert len(conversations.completed) == 1
    assert conversations.completed[0][3]["content"] == MARKDOWN_ANSWER


def test_stream_sends_keepalive_during_delayed_generation(monkeypatch):
    class DelayedService(FakeService):
        async def stream_answer(self, tenant_id, user_id, payload, request_id, **kwargs):
            yield {
                "event": "retrieval",
                "data": {"result_count": 1, "included_count": 1, "top_k": 8},
            }
            await asyncio.sleep(0.03)
            yield {"event": "token", "data": {"text": "Answer [C1]"}}
            yield {"event": "citations", "data": {"citations": []}}
            yield {
                "event": "complete",
                "data": {"grounded": True, "request_id": request_id},
            }

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.SSE_KEEPALIVE_SECONDS", 0.005
    )
    response = TestClient(app(service=DelayedService())).post(
        "/api/v1/tenant/ai/answer/stream", json={"query": "How?"}
    )
    assert response.status_code == 200
    assert ": keepalive\n\n" in response.text
    assert "event: complete" in response.text


def test_stream_converts_unexpected_eof_to_terminal_error():
    class IncompleteService(FakeService):
        async def stream_answer(self, tenant_id, user_id, payload, request_id, **kwargs):
            yield {
                "event": "retrieval",
                "data": {"result_count": 1, "included_count": 1, "top_k": 8},
            }

    conversations = FakeConversationService()
    response = TestClient(app(
        service=IncompleteService(), conversation_service=conversations
    )).post(
        "/api/v1/tenant/ai/answer/stream", json={"query": "How?"}
    )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "event: complete" not in response.text
    assert conversations.terminated[0][3]["status"].value == "failed"


def test_payload_cannot_supply_tenant_identity():
    response = TestClient(app()).post(
        "/api/v1/tenant/ai/answer",
        json={"query": "How?", "tenant_id": str(uuid4())},
    )
    assert response.status_code == 422


def test_top_k_and_empty_query_are_bounded():
    client = TestClient(app())
    assert client.post(
        "/api/v1/tenant/ai/answer", json={"query": "How?", "top_k": 51}
    ).status_code == 422
    assert client.post(
        "/api/v1/tenant/ai/answer", json={"query": "   "}
    ).status_code == 422


def test_unauthenticated_answer_is_rejected():
    response = TestClient(app(authenticated=False)).post(
        "/api/v1/tenant/ai/answer", json={"query": "How?"}
    )
    assert response.status_code == 401
