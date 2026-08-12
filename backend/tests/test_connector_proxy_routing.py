from datetime import UTC, datetime, timedelta
import logging
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
from app.core.logging import connector_id_ctx, tenant_id_ctx
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

    @app.middleware("http")
    async def expose_bound_connector_context(request, call_next):
        response = await call_next(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        connector_id = getattr(request.state, "connector_id", None)
        if tenant_id is not None:
            response.headers["X-Test-Context-Tenant"] = str(tenant_id)
        if connector_id is not None:
            response.headers["X-Test-Context-Connector"] = str(connector_id)
        return response

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


def test_operational_tool_claim_requires_connector_auth_and_consumes_claim(
    proxy_app, caplog
):
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
    caplog.set_level("WARNING", logger="app.middleware.tenant_context")
    caplog.clear()
    claimed = client.get(path, headers={**headers, "host": "127.0.0.1:8000"})
    assert claimed.status_code == 200
    assert claimed.json()["tool_name"] == "count_assets"
    assert "No tenant found for host" not in caplog.text
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


def test_empty_operational_tool_poll_is_tenant_neutral_and_binds_connector_tenant(
    proxy_app, caplog, monkeypatch
):
    client, service, tenant, _, admin = proxy_app
    body = registration_body(create_token(service, tenant, admin))
    body["capabilities"].append("operational_tools")
    registered = service.register(ConnectorRegistrationRequest.model_validate(body))
    connector = service.repository.get(tenant.id, registered.connector_id)
    connector.last_seen_at = datetime.now(UTC)
    connector.status = ManagedConnectorStatus.CONNECTED
    service.repository.commit()

    observed: dict[str, str] = {}
    original_claim = OperationalToolService.claim

    def observed_claim(tool_service, authenticated_connector):
        observed["tenant_id"] = tenant_id_ctx.get()
        observed["connector_id"] = connector_id_ctx.get()
        observed["record_tenant_id"] = str(authenticated_connector.tenant_id)
        return original_claim(tool_service, authenticated_connector)

    monkeypatch.setattr(OperationalToolService, "claim", observed_claim)
    caplog.set_level(logging.WARNING, logger="app.middleware.tenant_context")
    response = client.get(
        f"/api/v1/connectors/{registered.connector_id}/operational-tools/requests/next",
        headers={
            "host": "127.0.0.1:8000",
            "Authorization": f"Bearer {registered.connector_secret}",
            "X-PEKA-Connector-ID": str(registered.connector_id),
        },
    )

    assert response.status_code == 204
    assert "No tenant found for host" not in caplog.text
    assert response.headers["X-Test-Context-Tenant"] == str(tenant.id)
    assert response.headers["X-Test-Context-Connector"] == str(registered.connector_id)
    assert observed == {
        "tenant_id": str(tenant.id),
        "connector_id": str(registered.connector_id),
        "record_tenant_id": str(tenant.id),
    }


def test_connector_cannot_claim_another_tenants_operational_request(proxy_app):
    client, service, tenant_a, _, admin_a = proxy_app
    tenant_b = Tenant(
        slug="tenant-b",
        name="Tenant B",
        display_name="Tenant B",
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    service.repository.db.add(tenant_b)
    service.repository.db.flush()
    admin_b = TenantUser(
        tenant_id=tenant_b.id,
        username="admin-b",
        email="admin@tenant-b.test",
        full_name="Admin B",
        auth_source=TenantUserAuthSource.LOCAL,
        password_hash="unused",
        is_active=True,
        role=TenantUserRole.TENANT_ADMIN,
    )
    service.repository.db.add(admin_b)
    service.repository.db.commit()

    def register_for(tenant, admin):
        body = registration_body(create_token(service, tenant, admin))
        body["capabilities"].append("operational_tools")
        registered = service.register(ConnectorRegistrationRequest.model_validate(body))
        connector = service.repository.get(tenant.id, registered.connector_id)
        connector.last_seen_at = datetime.now(UTC)
        connector.status = ManagedConnectorStatus.CONNECTED
        service.repository.commit()
        return registered

    connector_a = register_for(tenant_a, admin_a)
    connector_b = register_for(tenant_b, admin_b)
    pending = OperationalToolService(service.repository.db).create(
        tenant_a.id, admin_a.id, "count_assets", {}
    )
    path_b = (
        f"/api/v1/connectors/{connector_b.connector_id}"
        "/operational-tools/requests/next"
        f"?tenant_id={tenant_a.id}"
    )
    response_b = client.get(
        path_b,
        headers={
            "Authorization": f"Bearer {connector_b.connector_secret}",
            "X-PEKA-Connector-ID": str(connector_b.connector_id),
            "X-Tenant-ID": str(tenant_a.id),
        },
    )
    assert response_b.status_code == 204

    response_a = client.get(
        f"/api/v1/connectors/{connector_a.connector_id}/operational-tools/requests/next",
        headers={
            "Authorization": f"Bearer {connector_a.connector_secret}",
            "X-PEKA-Connector-ID": str(connector_a.connector_id),
        },
    )
    assert response_a.status_code == 200
    assert response_a.json()["id"] == str(pending.id)


def test_saas_connector_document_upload_route_is_removed(proxy_app):
    client, service, tenant, _, admin = proxy_app
    registered = service.register(ConnectorRegistrationRequest.model_validate(
        registration_body(create_token(service, tenant, admin))
    ))
    response = client.post(
        f"/api/v1/connectors/{registered.connector_id}/documents",
        headers={
            "Authorization": f"Bearer {registered.connector_secret}",
            "X-PEKA-Connector-ID": str(registered.connector_id), "Idempotency-Key": "proxy-upload-0001",
        },
        data={"metadata": "{}"},
        files={"file": ("manual.txt", b"must remain local", "text/plain")},
    )
    assert response.status_code == 404


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
