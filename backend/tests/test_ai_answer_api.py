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
from app.services.assistant_operational import OperationalAnswer

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
    def __init__(self, operational_context=None):
        self.completed = []
        self.terminated = []
        self.operational_context = operational_context

    def begin_message(
        self, tenant_id, user_id, question, conversation_id=None, **kwargs
    ):
        return SimpleNamespace(id=conversation_id or uuid4()), SimpleNamespace(id=uuid4())

    def generation_context(self, tenant_id, user_id, conversation_id):
        return SimpleNamespace(
            text="",
            message_ids=[],
            operational_context=self.operational_context,
        )

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


def test_prompt_suggestions_use_connector_knowledge_summary():
    class KnowledgeSummaryDb:
        def scalar(self, _statement):
            return SimpleNamespace(local_knowledge_store_status="healthy")

    value = app()
    value.dependency_overrides[get_db] = KnowledgeSummaryDb
    response = TestClient(value).get("/api/v1/tenant/ai/suggestions")
    assert response.status_code == 200
    assert response.json() == {
        "has_indexed_knowledge": True,
        "suggestions": [
            "Summarize the available operational guidance.",
            "What troubleshooting procedures are documented?",
            "What should I know before making a production change?",
        ],
        "onboarding_guidance": None,
    }


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


def test_streaming_inventory_question_uses_operational_tool_not_document_search(
    monkeypatch,
):
    class FakeOperational:
        def __init__(self, _db):
            pass

        async def answer(self, tenant_id, user_id, intent):
            assert intent.tool_name == "count_assets"
            assert intent.arguments == {"os_family": "linux"}
            return OperationalAnswer(
                "You have 14 Linux servers in the current inventory.",
                "count_assets",
                uuid4(),
                {"count": 14},
            )

    class DocumentServiceMustNotRun(FakeService):
        async def stream_answer(self, *args, **kwargs):
            raise AssertionError("Document retrieval must not handle inventory counts")
            yield

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.OperationalAssistantService",
        FakeOperational,
    )
    conversations = FakeConversationService()
    response = TestClient(
        app(
            service=DocumentServiceMustNotRun(),
            conversation_service=conversations,
        )
    ).post(
        "/api/v1/tenant/ai/answer/stream",
        json={"query": "How many Linux servers do I have?"},
    )

    assert response.status_code == 200
    assert "You have 14 Linux servers" in response.text
    assert '"source":"connector"' in response.text
    assert '"tool_name":"count_assets"' in response.text
    assert conversations.completed[0][3]["prompt_version"] == "operational-tools-v1"


def test_streaming_followup_reuses_operational_count_context(monkeypatch):
    class FakeOperational:
        def __init__(self, _db):
            pass

        async def answer(self, tenant_id, user_id, intent):
            assert intent.tool_name == "search_assets"
            assert intent.arguments["os_family"] == "linux"
            return OperationalAnswer(
                "### Matching servers\n\n- **util001**",
                "search_assets",
                uuid4(),
                {"assets": [{"hostname": "util001"}]},
            )

    class DocumentServiceMustNotRun(FakeService):
        async def stream_answer(self, *args, **kwargs):
            raise AssertionError("Document retrieval must not handle operational follow-ups")
            yield

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.OperationalAssistantService",
        FakeOperational,
    )
    conversations = FakeConversationService(
        operational_context={
            "tool_name": "count_assets",
            "arguments": {"os_family": "linux"},
        }
    )
    response = TestClient(
        app(
            service=DocumentServiceMustNotRun(),
            conversation_service=conversations,
        )
    ).post(
        "/api/v1/tenant/ai/answer/stream",
        json={"query": "Which ones?", "conversation_id": str(uuid4())},
    )

    assert response.status_code == 200
    assert "util001" in response.text
    retrieval = conversations.completed[0][3]["retrieval"]
    assert retrieval["operational_context"]["tool_name"] == "search_assets"
    assert retrieval["operational_context"]["arguments"]["os_family"] == "linux"


def test_streaming_clarification_persists_pending_operational_intent(monkeypatch):
    class FakeOperational:
        def __init__(self, _db):
            pass

        async def answer(self, tenant_id, user_id, intent):
            assert intent.destination == "clarification"
            assert intent.tool_name == "get_asset_log_evidence"
            return OperationalAnswer(
                "Which server should I check for log evidence?",
                "clarification",
                None,
                None,
            )

    class DocumentServiceMustNotRun(FakeService):
        async def stream_answer(self, *args, **kwargs):
            raise AssertionError("Document retrieval must not handle pending errors")
            yield

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.OperationalAssistantService",
        FakeOperational,
    )
    conversations = FakeConversationService()
    response = TestClient(
        app(
            service=DocumentServiceMustNotRun(),
            conversation_service=conversations,
        )
    ).post(
        "/api/v1/tenant/ai/answer/stream",
        json={"query": "Any errors?"},
    )

    assert response.status_code == 200
    assert "Which server" in response.text
    context = conversations.completed[0][3]["retrieval"]["operational_context"]
    assert context == {
        "tool_name": "get_asset_log_evidence",
        "arguments": {"category": "errors", "lookback_hours": 24},
        "pending": True,
        "intent_family": "errors",
    }


def test_streaming_asset_reply_executes_pending_errors_not_document_rag(monkeypatch):
    class FakeOperational:
        def __init__(self, _db):
            pass

        async def answer(self, tenant_id, user_id, intent):
            assert intent.destination == "operational"
            assert intent.tool_name == "get_asset_log_evidence"
            assert intent.arguments == {
                "category": "errors",
                "lookback_hours": 24,
                "identifier": "util001",
            }
            return OperationalAnswer(
                "## Log evidence — util001\n\n- No relevant errors found.",
                "get_asset_log_evidence",
                uuid4(),
                {"match_status": "found"},
            )

    class DocumentServiceMustNotRun(FakeService):
        async def stream_answer(self, *args, **kwargs):
            raise AssertionError("Document retrieval must not handle the pending asset reply")
            yield

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.OperationalAssistantService",
        FakeOperational,
    )
    conversations = FakeConversationService(
        operational_context={
            "tool_name": "get_asset_log_evidence",
            "arguments": {"category": "errors", "lookback_hours": 24},
            "pending": True,
            "intent_family": "errors",
        }
    )
    response = TestClient(
        app(
            service=DocumentServiceMustNotRun(),
            conversation_service=conversations,
        )
    ).post(
        "/api/v1/tenant/ai/answer/stream",
        json={"query": "util001", "conversation_id": str(uuid4())},
    )

    assert response.status_code == 200
    assert "Log evidence" in response.text


def test_streaming_why_reuses_evidence_context_without_document_rag(monkeypatch):
    class FakeOperational:
        def __init__(self, _db):
            pass

        async def answer(self, tenant_id, user_id, intent):
            assert intent.destination == "contextual"
            assert intent.tool_name == "reuse_operational_evidence"
            assert intent.arguments == {"action": "explain"}
            return OperationalAnswer(
                "## Explanation — util001\n\n- **Why:** CPU was above threshold.",
                "reuse_operational_evidence",
                None,
                None,
            )

    class DocumentServiceMustNotRun(FakeService):
        async def stream_answer(self, *args, **kwargs):
            raise AssertionError("Document retrieval must not handle operational explanations")
            yield

    monkeypatch.setattr(
        "app.api.routes.tenant.ai_answer.OperationalAssistantService",
        FakeOperational,
    )
    prior = {
        "tool_name": "get_asset_status",
        "arguments": {"identifier": "util001", "mode": "health"},
        "pending": False,
        "intent_family": "health",
        "active_identifier": "util001",
        "evidence_snapshot": {
            "identifier": "util001",
            "assessment": {
                "conclusion": "CPU was above threshold.",
                "evidence": ["CPU utilization was 92%."],
            },
            "utilization": {"metric_timestamp": "2026-07-30T12:00:00Z"},
        },
    }
    conversations = FakeConversationService(operational_context=prior)
    response = TestClient(
        app(
            service=DocumentServiceMustNotRun(),
            conversation_service=conversations,
        )
    ).post(
        "/api/v1/tenant/ai/answer/stream",
        json={"query": "Why?", "conversation_id": str(uuid4())},
    )

    assert response.status_code == 200
    assert "CPU was above threshold" in response.text
    stored = conversations.completed[0][3]["retrieval"]["operational_context"]
    assert stored["active_identifier"] == "util001"
    assert stored["evidence_snapshot"] == prior["evidence_snapshot"]


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
