from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import allow_tenant_user
from app.api.dependencies import get_ai_conversation_service
from app.api.routes.tenant.ai_conversations import router
from app.api.tenant_context import get_current_tenant_context
from app.db.base import Base
from app.repositories.ai_conversation_repository import AIConversationRepository
from app.services.ai_conversation_service import AIConversationService


def test_conversation_api_returns_404_for_same_tenant_admin_and_cross_tenant():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    service = AIConversationService(AIConversationRepository(db))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    identity = {
        "tenant_id": uuid4(),
        "user_id": uuid4(),
        "role": "tenant_user",
    }
    app.dependency_overrides[get_current_tenant_context] = lambda: SimpleNamespace(
        tenant_id=identity["tenant_id"]
    )
    app.dependency_overrides[allow_tenant_user] = lambda: SimpleNamespace(
        id=identity["user_id"], role=identity["role"]
    )
    app.dependency_overrides[get_ai_conversation_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/api/v1/tenant/ai/conversations", json={"title": "Owner chat"}
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert client.get(
        f"/api/v1/tenant/ai/conversations/{conversation_id}"
    ).status_code == 200
    assert client.get(
        "/api/v1/tenant/ai/conversations"
    ).json()["total"] == 1

    identity["user_id"] = uuid4()
    identity["role"] = "tenant_admin"
    assert client.get(
        f"/api/v1/tenant/ai/conversations/{conversation_id}"
    ).status_code == 404
    assert client.patch(
        f"/api/v1/tenant/ai/conversations/{conversation_id}/title",
        json={"title": "Admin cannot rename"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/tenant/ai/conversations/{conversation_id}"
    ).status_code == 404
    assert client.get(
        "/api/v1/tenant/ai/conversations"
    ).json()["total"] == 0

    identity["tenant_id"] = uuid4()
    identity["user_id"] = uuid4()
    assert client.get(
        f"/api/v1/tenant/ai/conversations/{conversation_id}"
    ).status_code == 404
    assert client.patch(
        f"/api/v1/tenant/ai/conversations/{conversation_id}/archive",
        json={"is_archived": True},
    ).status_code == 404


def test_citation_evidence_api_never_reads_outside_owned_stored_message():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    service = AIConversationService(AIConversationRepository(db))
    tenant_id, user_id = uuid4(), uuid4()
    conversation, assistant = service.begin_message(
        tenant_id, user_id, "Question"
    )
    service.complete(
        tenant_id, user_id, assistant.id, content="Answer [C1]",
        citations=[{
            "citation_id": "C1", "source_type": "document",
            "document_id": str(uuid4()), "version_id": str(uuid4()),
            "chunk_id": str(uuid4()), "title": "Snapshot",
            "page_number": None, "section_title": "Evidence",
            "sheet_name": None, "row_start": None, "row_end": None,
            "score": 0.9, "excerpt": "Stored supporting excerpt.",
            "revision": "sha256:snapshot",
            "sensitive_content_redacted": False,
        }],
        retrieval={}, model="test", prompt_version="v1",
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    identity = {"tenant_id": tenant_id, "user_id": user_id}
    app.dependency_overrides[get_current_tenant_context] = lambda: SimpleNamespace(
        tenant_id=identity["tenant_id"]
    )
    app.dependency_overrides[allow_tenant_user] = lambda: SimpleNamespace(
        id=identity["user_id"]
    )
    app.dependency_overrides[get_ai_conversation_service] = lambda: service
    client = TestClient(app)
    path = (
        f"/api/v1/tenant/ai/conversations/{conversation.id}/messages/"
        f"{assistant.id}/citations/C1"
    )
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["citation"]["excerpt"] == "Stored supporting excerpt."
    assert response.json()["citation"]["revision"] == "sha256:snapshot"
    identity["user_id"] = uuid4()
    assert client.get(path).status_code == 404
    identity["tenant_id"] = uuid4()
    assert client.get(path).status_code == 404
