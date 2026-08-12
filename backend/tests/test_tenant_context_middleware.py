import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.core.tenant_definition import TenantDefinition
from app.core.logging import tenant_id_ctx
from app.core.tenant_registry import TenantRegistry
from app.middleware.tenant_context import (
    RequestTenancy,
    TenantContextMiddleware,
    classify_request_tenancy,
)


def build_app(mode: str) -> tuple[FastAPI, TenantDefinition]:
    registry = TenantRegistry()
    definition = TenantDefinition(
        tenant_id=uuid4(),
        slug="vitwo",
        hostname="vitwo.peka.com",
        enabled=True,
    )
    registry.add(definition)

    app = FastAPI()

    @app.get("/api/v1/tenant/probe")
    def probe(request: Request) -> dict[str, str]:
        context = getattr(request.state, "tenant_context", None)
        if context is None:
            raise HTTPException(status_code=404, detail="Tenant could not be resolved.")
        return {
            "slug": context.slug,
            "tenant_id": str(request.state.tenant_id),
            "logging_tenant_id": tenant_id_ctx.get(),
            "path": request.scope["path"],
            "query": request.url.query,
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/platform/probe")
    def platform_probe() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        TenantContextMiddleware,
        registry=registry,
        tenant_url_mode=mode,
    )
    return app, definition


def test_path_mode_resolves_tenant_and_strips_prefix() -> None:
    app, definition = build_app("path")

    response = TestClient(app).get(
        "/t/vitwo/api/v1/tenant/probe?next=%2Fdashboard"
    )

    assert response.status_code == 200
    assert response.json() == {
        "slug": definition.slug,
        "tenant_id": str(definition.tenant_id),
        "logging_tenant_id": str(definition.tenant_id),
        "path": "/api/v1/tenant/probe",
        "query": "next=%2Fdashboard",
    }


def test_path_mode_unknown_tenant_slug_is_not_routed() -> None:
    app, _ = build_app("path")

    response = TestClient(app).get("/t/unknown/api/v1/tenant/probe")

    assert response.status_code == 404


def test_hostname_mode_remains_unchanged() -> None:
    app, definition = build_app("subdomain")

    response = TestClient(app).get(
        "/api/v1/tenant/probe",
        headers={"host": "vitwo.peka.com"},
    )

    assert response.status_code == 200
    assert response.json()["slug"] == definition.slug
    assert response.json()["path"] == "/api/v1/tenant/probe"


def test_unknown_hostname_on_tenant_route_still_warns(caplog) -> None:
    app, _ = build_app("subdomain")
    caplog.set_level(logging.WARNING, logger="app.middleware.tenant_context")

    response = TestClient(app).get(
        "/api/v1/tenant/probe",
        headers={"host": "unknown.peka.example"},
    )

    assert response.status_code == 404
    assert "No tenant found for host 'unknown.peka.example'" in caplog.text


def test_health_and_platform_routes_do_not_resolve_tenant_host(caplog) -> None:
    app, _ = build_app("subdomain")
    client = TestClient(app)
    caplog.set_level(logging.WARNING, logger="app.middleware.tenant_context")

    health = client.get("/health", headers={"host": "localhost:8000"})
    platform = client.get(
        "/api/v1/platform/probe",
        headers={"host": "127.0.0.1:8000"},
    )

    assert health.status_code == 200
    assert platform.status_code == 200
    assert "No tenant found for host" not in caplog.text


def test_request_tenancy_classification_has_explicit_route_boundaries() -> None:
    connector_id = "7c540c00-5fb5-4fec-87ee-1b43e6c0cdac"
    connector_paths = (
        "/api/v1/connectors/register",
        f"/api/v1/connectors/{connector_id}/heartbeat",
        f"/api/v1/connectors/{connector_id}/documents",
        f"/api/v1/connectors/{connector_id}/documents/status",
        f"/api/v1/connectors/{connector_id}/reconciliation",
        f"/api/v1/connectors/{connector_id}/operational-tools/requests/next",
        f"/api/v1/connectors/{connector_id}/operational-tools/requests/request-id/result",
    )

    assert classify_request_tenancy(connector_paths[0]) is RequestTenancy.CONNECTOR_REGISTRATION
    for path in connector_paths[1:]:
        assert classify_request_tenancy(path) is RequestTenancy.CONNECTOR_AUTHENTICATED
    assert classify_request_tenancy("/api/v1/connectors-internal") is RequestTenancy.TENANT_HOST
    assert classify_request_tenancy("/healthcheck") is RequestTenancy.TENANT_HOST


def test_hostname_mode_does_not_strip_path_prefix() -> None:
    app, _ = build_app("subdomain")

    response = TestClient(app).get(
        "/t/vitwo/api/v1/tenant/probe",
        headers={"host": "vitwo.peka.com"},
    )

    assert response.status_code == 404
