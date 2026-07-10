from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.tenant_definition import TenantDefinition
from app.core.logging import tenant_id_ctx
from app.core.tenant_registry import TenantRegistry
from app.middleware.tenant_context import TenantContextMiddleware


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
        context = request.state.tenant_context
        return {
            "slug": context.slug,
            "tenant_id": str(request.state.tenant_id),
            "logging_tenant_id": tenant_id_ctx.get(),
            "path": request.scope["path"],
            "query": request.url.query,
        }

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


def test_hostname_mode_does_not_strip_path_prefix() -> None:
    app, _ = build_app("subdomain")

    response = TestClient(app).get(
        "/t/vitwo/api/v1/tenant/probe",
        headers={"host": "vitwo.peka.com"},
    )

    assert response.status_code == 404
