from datetime import UTC, datetime, timedelta
import json
import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_connector_service
from app.db.session import get_db
from app.api.routes.connectors import (
    connector_registration_validation_handler,
    router as connector_router,
)
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.core.tenant_definition import TenantDefinition
from app.core.tenant_registry import TenantRegistry
from app.db.base import Base
from app.middleware.tenant_context import TenantContextMiddleware
from app.models.tenant import Tenant, TenantStatus
from app.models.connector import ManagedConnectorStatus
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.tenant_repository import TenantRepository
from app.schemas.connector_api import ConnectorRegistrationRequest
from app.services.connector_service import ConnectorService
from app.services.operational_tool_service import OperationalToolService


@pytest.fixture()
def proxy_app(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.routes.connectors.registration_limiter.allow", lambda _key: True)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(
        slug="token-tenant",
        name="Token Tenant",
        display_name="Token Tenant",
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    routing_tenant = Tenant(
        slug="routing-tenant",
        name="Routing Tenant",
        display_name="Routing Tenant",
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    db.add_all([tenant, routing_tenant])
    db.flush()
    admin = TenantUser(
        tenant_id=tenant.id,
        username="admin",
        email="admin@token-tenant.test",
        full_name="Admin",
        auth_source=TenantUserAuthSource.LOCAL,
        password_hash="unused",
        is_active=True,
        role=TenantUserRole.TENANT_ADMIN,
    )
    db.add(admin)
    db.commit()

    service = ConnectorService(ConnectorRepository(db), TenantRepository(db))
    registry = TenantRegistry()
    registry.add(TenantDefinition(
        tenant_id=routing_tenant.id,
        slug=routing_tenant.slug,
        hostname="routing-tenant.example.test",
        enabled=True,
    ))
    app = FastAPI()
    app.include_router(connector_router, prefix="/api/v1")
    app.add_exception_handler(
        RequestValidationError,
        connector_registration_validation_handler,
    )

    @app.get("/api/v1/tenant/probe")
    def tenant_probe(context: TenantContext = Depends(get_current_tenant_context)):
        return {"tenant_id": str(context.tenant_id)}

    app.dependency_overrides[get_connector_service] = lambda: service
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr("app.api.routes.connectors.settings.peka_object_storage_local_root", str(tmp_path))
    app.add_middleware(
        TenantContextMiddleware,
        registry=registry,
        tenant_url_mode="subdomain",
    )
    client = TestClient(app)
    yield client, service, tenant, routing_tenant, admin
    client.close()
    db.close()
    engine.dispose()


def registration_body(raw_token: str, *, instance_id: UUID | None = None) -> dict:
    return {
        "registration_token": raw_token,
        "connector_name": "proxy-connector",
        "connector_version": "1.0.0",
        "environment": "production",
        "instance_id": str(instance_id or uuid4()),
        "capabilities": ["filesystem_documents"],
    }


def test_operational_tool_claim_requires_connector_auth_and_consumes_claim(proxy_app):
    client, connector_service, tenant, _, admin = proxy_app
    body = registration_body(create_token(connector_service, tenant, admin))
    body["capabilities"].append("operational_tools")
    registered = connector_service.register(
        ConnectorRegistrationRequest.model_validate(body)
    )
    connector = connector_service.repository.get(tenant.id, registered.connector_id)
    connector.last_seen_at = datetime.now(UTC)
    connector.status = ManagedConnectorStatus.CONNECTED
    connector_service.repository.commit()
    request = OperationalToolService(connector_service.repository.db).create(
        tenant.id,
        admin.id,
        "count_assets",
        {"os_family": "linux"},
    )
    path = (
        f"/api/v1/connectors/{registered.connector_id}"
        "/operational-tools/requests/next"
    )

    unauthorized = client.get(
        path,
        headers={
            "Authorization": "Bearer invalid",
            "X-PEKA-Connector-ID": str(registered.connector_id),
        },
    )
    assert unauthorized.status_code == 401

    headers = {
        "Authorization": f"Bearer {registered.connector_secret}",
        "X-PEKA-Connector-ID": str(registered.connector_id),
    }
    claimed = client.get(path, headers=headers)
    assert claimed.status_code == 200
    assert claimed.json()["tool_name"] == "count_assets"
    result_path = (
        f"/api/v1/connectors/{registered.connector_id}"
        f"/operational-tools/requests/{request.id}/result"
    )
    submission = {
        "claim_token": claimed.json()["claim_token"],
        "status": "completed",
        "result": {"count": 14},
    }
    assert client.post(result_path, headers=headers, json=submission).status_code == 204
    assert client.post(result_path, headers=headers, json=submission).status_code == 409


def test_document_upload_succeeds_with_proxy_host_and_connector_identity(proxy_app, caplog):
    import hashlib

    client, service, tenant, _, admin = proxy_app
    registered = service.register(ConnectorRegistrationRequest.model_validate(
        registration_body(create_token(service, tenant, admin))
    ))
    content = b"Connector document content"
    metadata = {
        "source_id": "filesystem-main", "document_key": "manual.txt",
        "relative_path": "manual.txt", "filename": "manual.txt", "mime_type": "text/plain",
        "size_bytes": len(content), "content_hash": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "modified_at": datetime.now(UTC).isoformat(), "operation": "upsert",
        "connector_version": "1.0.0",
    }
    response = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents",
        headers={
            "host": "backend.internal:8000", "Authorization": f"Bearer {registered.connector_secret}",
            "X-PEKA-Connector-ID": str(registered.connector_id), "Idempotency-Key": "proxy-upload-0001",
        },
        data={"metadata": json.dumps(metadata)},
        files={"file": ("manual.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["accepted"] is True
    assert "tenant_id" not in response.json()
    assert registered.connector_secret not in caplog.text
    assert content.decode() not in caplog.text


@pytest.mark.parametrize(("filename", "mime_type"), [
    ("notes.txt", "text/plain"),
    ("readme.md", "text/markdown"),
    ("inventory.csv", "text/csv"),
    ("manual.pdf", "application/pdf"),
    ("policy.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("assets.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
])
def test_connector_api_accepts_supported_document_formats(proxy_app, filename, mime_type):
    client, service, tenant, _, admin = proxy_app
    registered = _registered_document_connector(service, tenant, admin)
    content = f"verified upload for {filename}".encode()
    response = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents",
        headers={
            "Authorization": f"Bearer {registered.connector_secret}",
            "X-PEKA-Connector-ID": str(registered.connector_id),
            "Idempotency-Key": f"format-{filename}",
        },
        data={"metadata": json.dumps(_document_metadata(
            content, document_key=filename, relative_path=filename,
            filename=filename, mime_type=mime_type,
        ))},
        files={"file": (filename, content, mime_type)},
    )
    assert response.status_code == 201
    assert response.json()["content_hash"] == f"sha256:{hashlib.sha256(content).hexdigest()}"


def _registered_document_connector(service, tenant, admin):
    return service.register(ConnectorRegistrationRequest.model_validate(
        registration_body(create_token(service, tenant, admin))
    ))


def _document_metadata(content: bytes, **overrides):
    import hashlib

    body = {
        "source_id": "filesystem-main", "document_key": "manual.txt",
        "relative_path": "manual.txt", "filename": "manual.txt", "mime_type": "text/plain",
        "size_bytes": len(content), "content_hash": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "modified_at": datetime.now(UTC).isoformat(), "operation": "upsert",
        "connector_version": "1.0.0",
    }
    body.update(overrides)
    return body


def _upload(client, registered, metadata, content=b"safe content", **headers):
    return client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents",
        headers={
            "Authorization": f"Bearer {registered.connector_secret}",
            "X-PEKA-Connector-ID": str(registered.connector_id),
            "Idempotency-Key": f"document-{uuid4()}",
            **headers,
        },
        data={"metadata": json.dumps(metadata)},
        files={"file": (metadata.get("filename", "manual.txt"), content, "text/plain")},
    )


def test_document_upload_structured_security_errors(proxy_app):
    client, service, tenant, _, admin = proxy_app
    registered = _registered_document_connector(service, tenant, admin)
    content = b"safe content"
    metadata = _document_metadata(content)

    invalid = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents",
        headers={"Authorization": "Bearer invalid", "X-PEKA-Connector-ID": str(registered.connector_id),
                 "Idempotency-Key": "document-invalid-secret"},
        data={"metadata": json.dumps(metadata)}, files={"file": ("manual.txt", content, "text/plain")},
    )
    assert invalid.status_code == 401
    assert invalid.json() == {"code": "INVALID_CONNECTOR", "message": "Connector authentication failed."}

    tenant_override = _upload(
        client, registered, {**metadata, "tenant_id": str(uuid4())}, content,
        host="backend.proxy.internal", **{"X-Forwarded-Host": "other-tenant.example"},
    )
    assert tenant_override.status_code == 422
    assert tenant_override.json()["code"] == "INVALID_DOCUMENT_METADATA"

    connector = service.repository.get(tenant.id, registered.connector_id)
    connector.retired_at = datetime.now(UTC); service.repository.commit()
    retired = _upload(client, registered, metadata, content)
    assert retired.status_code == 403
    assert retired.json()["code"] == "CONNECTOR_RETIRED"

    connector.retired_at = None
    connector.status = ManagedConnectorStatus.AUTHENTICATION_FAILED
    service.repository.commit()
    locked = _upload(client, registered, metadata, content)
    assert locked.status_code == 403
    assert locked.json()["code"] == "INVALID_CONNECTOR"


def test_document_upload_reports_hash_size_mime_and_idempotency_conflicts(proxy_app):
    client, service, tenant, _, admin = proxy_app
    registered = _registered_document_connector(service, tenant, admin)
    content = b"safe content"
    headers = {
        "Authorization": f"Bearer {registered.connector_secret}",
        "X-PEKA-Connector-ID": str(registered.connector_id),
        "Idempotency-Key": "document-stable-key",
    }
    metadata = _document_metadata(content)
    first = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents", headers=headers,
        data={"metadata": json.dumps(metadata)}, files={"file": ("manual.txt", content, "text/plain")},
    )
    assert first.status_code == 201
    replay = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents", headers=headers,
        data={"metadata": json.dumps(metadata)}, files={"file": ("manual.txt", content, "text/plain")},
    )
    assert replay.status_code == 201 and replay.json() == first.json()
    conflict = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents", headers=headers,
        data={"metadata": json.dumps({**metadata, "filename": "changed.txt"})},
        files={"file": ("changed.txt", content, "text/plain")},
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    mismatch = _upload(client, registered, {**metadata, "size_bytes": len(content) + 1}, content)
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "SIZE_MISMATCH"
    hash_mismatch = _upload(client, registered, {**metadata, "content_hash": "sha256:" + "0" * 64}, content)
    assert hash_mismatch.status_code == 422 and hash_mismatch.json()["code"] == "HASH_MISMATCH"
    mime_mismatch = _upload(client, registered, {**metadata, "mime_type": "application/pdf"}, content)
    assert mime_mismatch.status_code == 422 and mime_mismatch.json()["code"] == "MIME_MISMATCH"


def test_replacement_connector_can_tombstone_same_tenant_logical_document(proxy_app):
    client, service, tenant, _, admin = proxy_app
    owner = _registered_document_connector(service, tenant, admin)
    other = _registered_document_connector(service, tenant, admin)
    content = b"owned content"
    metadata = _document_metadata(content)
    assert _upload(client, owner, metadata, content).status_code == 201
    tombstone = {**metadata, "operation": "delete", "size_bytes": 0,
                 "content_hash": "sha256:" + hashlib.sha256(b"").hexdigest()}
    response = client.post(
        f"/api/v1/connectors/{other.connector_id}/documents",
        headers={"Authorization": f"Bearer {other.connector_secret}",
                 "X-PEKA-Connector-ID": str(other.connector_id),
                 "Idempotency-Key": "other-delete-key"},
        json=tombstone,
    )
    assert response.status_code == 201
    assert response.json()["ingestion_status"] == "DELETE_RECEIVED"

    connector_tombstone = {
        **metadata, "operation": "delete", "content_hash": None, "modified_at": None
    }
    delete_headers = {
        "Authorization": f"Bearer {owner.connector_secret}",
        "X-PEKA-Connector-ID": str(owner.connector_id),
        "Idempotency-Key": "owner-json-delete-key",
    }
    deleted = client.post(
        f"/api/v1/connectors/{owner.connector_id}/documents",
        headers=delete_headers, json=connector_tombstone,
    )
    replay = client.post(
        f"/api/v1/connectors/{owner.connector_id}/documents",
        headers=delete_headers, json=connector_tombstone,
    )
    assert deleted.status_code == 201
    assert deleted.json()["ingestion_status"] == "DELETE_RECEIVED"
    assert replay.json() == deleted.json()


def test_malformed_document_multipart_returns_structured_error(proxy_app):
    client, service, tenant, _, admin = proxy_app
    registered = _registered_document_connector(service, tenant, admin)
    response = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents",
        headers={"Authorization": f"Bearer {registered.connector_secret}",
                 "X-PEKA-Connector-ID": str(registered.connector_id),
                 "Idempotency-Key": "malformed-document-key"},
        files={"file": ("manual.txt", b"missing metadata", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def create_token(
    service: ConnectorService,
    tenant: Tenant,
    admin: TenantUser,
    intended_name: str | None = None,
) -> str:
    return service.create_registration_token(
        tenant.id,
        admin,
        intended_name,
    ).registration_token


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "peka-backend.internal:8000"])
def test_registration_succeeds_with_reverse_proxy_host(proxy_app, host):
    client, service, tenant, _, admin = proxy_app
    response = client.post(
        "/api/v1/connectors/register",
        headers={"host": host},
        json=registration_body(create_token(service, tenant, admin)),
    )
    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(tenant.id)


def test_intended_name_is_audit_metadata_not_registration_constraint(proxy_app):
    client, service, tenant, _, admin = proxy_app
    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(
            create_token(service, tenant, admin, "VITWO Connector II")
        ),
    )

    assert response.status_code == 201
    connector = service.repository.get(
        tenant.id,
        UUID(response.json()["connector_id"]),
    )
    assert connector is not None
    assert connector.name == "proxy-connector"


def test_registration_without_intended_name_succeeds(proxy_app):
    client, service, tenant, _, admin = proxy_app

    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(create_token(service, tenant, admin)),
    )

    assert response.status_code == 201


def test_invalid_token_still_fails_behind_proxy(proxy_app, caplog):
    client, _, _, _, _ = proxy_app
    raw_token = "peka_reg_invalid-but-long-enough"
    caplog.set_level("WARNING", logger="app.connector_registration")
    response = client.post(
        "/api/v1/connectors/register",
        headers={"host": "127.0.0.1:8000"},
        json=registration_body(raw_token),
    )
    assert response.status_code == 401
    assert response.json() == {
        "code": "TOKEN_NOT_FOUND",
        "message": "The registration token is invalid or not permitted.",
    }
    assert "connector_registration_token_validation_failed" in caplog.text
    assert "rejection_code=TOKEN_NOT_FOUND" in caplog.text
    assert raw_token not in caplog.text


def test_token_not_host_or_forwarded_host_determines_tenant(proxy_app):
    client, service, tenant, routing_tenant, admin = proxy_app
    response = client.post(
        "/api/v1/connectors/register",
        headers={
            "host": "routing-tenant.example.test",
            "x-forwarded-host": "routing-tenant.example.test",
        },
        json=registration_body(create_token(service, tenant, admin)),
    )
    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(tenant.id)
    assert response.json()["tenant_id"] != str(routing_tenant.id)


def test_registration_rejects_tenant_id_override(proxy_app):
    client, service, tenant, routing_tenant, admin = proxy_app
    body = registration_body(create_token(service, tenant, admin))
    body["tenant_id"] = str(routing_tenant.id)
    response = client.post(
        "/api/v1/connectors/register",
        headers={"host": "127.0.0.1:8000"},
        json=body,
    )
    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_FAILED",
        "message": "The connector registration request is invalid.",
    }


def test_registration_rejects_invalid_connector_name(proxy_app):
    client, service, tenant, _, admin = proxy_app
    body = registration_body(create_token(service, tenant, admin))
    body["connector_name"] = "invalid\nname"

    response = client.post("/api/v1/connectors/register", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_normal_tenant_route_still_requires_tenant_context(proxy_app):
    client, _, _, _, _ = proxy_app
    response = client.get(
        "/api/v1/tenant/probe",
        headers={"host": "127.0.0.1:8000"},
    )
    assert response.status_code == 404


def test_heartbeat_succeeds_behind_reverse_proxy(proxy_app):
    client, service, tenant, _, admin = proxy_app
    instance_id = uuid4()
    registration = client.post(
        "/api/v1/connectors/register",
        headers={"host": "localhost:8000"},
        json=registration_body(
            create_token(service, tenant, admin), instance_id=instance_id
        ),
    ).json()
    connector_id = registration["connector_id"]
    response = client.post(
        f"/api/v1/connectors/{connector_id}/heartbeat",
        headers={
            "host": "peka-backend.internal:8000",
            "x-forwarded-host": "routing-tenant.example.test",
            "authorization": f"Bearer {registration['connector_secret']}",
            "x-peka-connector-id": connector_id,
        },
        json={
            "instance_id": str(instance_id),
            "name": "VITWO Production Connector",
            "connector_version": "1.0.0",
            "environment": "production-eu",
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "healthy",
            "uptime_seconds": 10,
            "sources": {
                "total": 1,
                "healthy": 1,
                "unhealthy": 0,
                "disabled": 0,
            },
            "capabilities": ["filesystem_documents"],
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    connector = service.repository.get(tenant.id, UUID(connector_id))
    assert connector is not None
    assert connector.name == "VITWO Production Connector"
    assert connector.environment == "production-eu"
    assert service.list_tenant_connectors(tenant.id)[0].name == "VITWO Production Connector"
    assert service.get_tenant_detail(tenant.id, connector.id).name == "VITWO Production Connector"


def test_expired_registration_token_returns_structured_gone(proxy_app):
    client, service, tenant, _, admin = proxy_app
    issued = service.create_registration_token(tenant.id, admin, None)
    token = service.repository.get_registration_token(tenant.id, issued.id)
    assert token is not None
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    service.repository.commit()

    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(issued.registration_token),
    )

    assert response.status_code == 410
    assert response.json() == {
        "code": "TOKEN_EXPIRED",
        "message": "The registration token has expired.",
    }


def test_used_registration_token_returns_structured_gone(proxy_app):
    client, service, tenant, _, admin = proxy_app
    raw_token = create_token(service, tenant, admin)
    body = registration_body(raw_token)
    assert client.post("/api/v1/connectors/register", json=body).status_code == 201

    response = client.post("/api/v1/connectors/register", json=body)

    assert response.status_code == 410
    assert response.json() == {
        "code": "TOKEN_USED",
        "message": "The registration token has already been used.",
    }


def test_revoked_registration_token_returns_structured_gone(proxy_app):
    client, service, tenant, _, admin = proxy_app
    issued = service.create_registration_token(tenant.id, admin, None)
    service.revoke_registration_token(tenant.id, issued.id, admin)

    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(issued.registration_token),
    )

    assert response.status_code == 410
    assert response.json() == {
        "code": "TOKEN_REVOKED",
        "message": "The registration token has been revoked.",
    }


def test_duplicate_active_instance_returns_specific_conflict(proxy_app):
    client, service, tenant, _, admin = proxy_app
    instance_id = UUID("3f04998c-953a-456d-891b-b68c3a097a92")
    first = client.post(
        "/api/v1/connectors/register",
        json=registration_body(
            create_token(service, tenant, admin),
            instance_id=instance_id,
        ),
    )
    assert first.status_code == 201

    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(
            create_token(service, tenant, admin),
            instance_id=instance_id,
        ),
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "INSTANCE_ALREADY_REGISTERED",
        "message": "This connector appliance is already registered.",
    }


def test_inactive_tenant_returns_specific_forbidden(proxy_app, caplog):
    client, service, tenant, _, admin = proxy_app
    raw_token = create_token(service, tenant, admin)
    tenant.status = TenantStatus.SUSPENDED
    service.repository.commit()
    caplog.set_level("WARNING", logger="app.connector_registration")

    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(raw_token),
    )

    assert response.status_code == 403
    assert response.json() == {
        "code": "TENANT_INACTIVE",
        "message": "Connector registration is not permitted for an inactive tenant.",
    }
    assert "internal_reason=tenant_suspended" in caplog.text


def test_connector_limit_returns_specific_conflict(proxy_app):
    client, service, tenant, _, admin = proxy_app
    first = client.post(
        "/api/v1/connectors/register",
        json=registration_body(create_token(service, tenant, admin)),
    )
    assert first.status_code == 201
    service.connector_limit = 1

    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(create_token(service, tenant, admin)),
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "CONNECTOR_LIMIT_REACHED",
        "message": "The tenant connector limit has been reached.",
    }


def test_unexpected_exception_is_not_mapped_to_not_permitted(proxy_app, caplog, monkeypatch):
    client, service, tenant, _, admin = proxy_app

    def fail_registration(_payload):
        raise RuntimeError("safe test failure")

    monkeypatch.setattr(service, "register", fail_registration)
    caplog.set_level("WARNING", logger="app.connector_registration")
    response = client.post(
        "/api/v1/connectors/register",
        json=registration_body(create_token(service, tenant, admin)),
    )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "REGISTRATION_NOT_PERMITTED" not in response.text
    assert "internal_reason=unexpected_RuntimeError" in caplog.text


def test_registration_logs_identifiers_but_never_credentials(proxy_app, caplog):
    client, service, tenant, _, admin = proxy_app
    instance_id = UUID("3f04998c-953a-456d-891b-b68c3a097a92")
    raw_token = create_token(service, tenant, admin)
    caplog.set_level("INFO", logger="app.connector_registration")

    response = client.post(
        "/api/v1/connectors/register",
        headers={"X-Request-ID": "registration-diagnostic-test"},
        json=registration_body(raw_token, instance_id=instance_id),
    )
    assert response.status_code == 201
    connector_secret = response.json()["connector_secret"]

    assert "connector_registration_request_received" in caplog.text
    assert "connector_registration_completed" in caplog.text
    assert "request_id=registration-diagnostic-test" in caplog.text
    assert f"instance_id={instance_id}" in caplog.text
    assert raw_token not in caplog.text
    assert connector_secret not in caplog.text


def test_rejection_log_contains_request_instance_and_exact_code(proxy_app, caplog):
    client, service, tenant, _, admin = proxy_app
    instance_id = UUID("3f04998c-953a-456d-891b-b68c3a097a92")
    first_token = create_token(service, tenant, admin)
    assert client.post(
        "/api/v1/connectors/register",
        json=registration_body(first_token, instance_id=instance_id),
    ).status_code == 201
    caplog.clear()
    caplog.set_level("WARNING", logger="app.connector_registration")

    response = client.post(
        "/api/v1/connectors/register",
        headers={"X-Request-ID": "duplicate-request-id"},
        json=registration_body(
            create_token(service, tenant, admin),
            instance_id=instance_id,
        ),
    )

    assert response.status_code == 409
    assert "connector_registration_duplicate_instance_detected" in caplog.text
    assert "request_id=duplicate-request-id" in caplog.text
    assert f"instance_id={instance_id}" in caplog.text
    assert f"tenant_id={tenant.id}" in caplog.text
    assert "registration_token_id=" in caplog.text
    assert "rejection_code=INSTANCE_ALREADY_REGISTERED" in caplog.text
