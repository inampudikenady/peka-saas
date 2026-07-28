from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.auth import require_tenant_admin
from app.api.dependencies import get_connector_service
from app.api.routes.tenant.connectors import router
from app.api.tenant_context import get_current_tenant_context


class FakeConnectorService:
    def list_tenant_connectors(self, tenant_id, *, include_retired=False):
        return []

    def list_registration_tokens(self, tenant_id, *, include_inactive=False):
        return []


def connector_app(*, administrator: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_tenant_context] = lambda: SimpleNamespace(
        tenant_id=uuid4()
    )
    app.dependency_overrides[get_connector_service] = FakeConnectorService
    if administrator:
        app.dependency_overrides[require_tenant_admin] = lambda: SimpleNamespace(
            id=uuid4(), role="tenant_admin"
        )
    else:
        def reject_normal_user():
            raise HTTPException(
                status_code=403,
                detail="Tenant administrator access required.",
            )

        app.dependency_overrides[require_tenant_admin] = reject_normal_user
    return app


def test_normal_tenant_user_cannot_read_connector_management_apis():
    client = TestClient(connector_app(administrator=False))
    for path in (
        "/api/v1/tenant/connectors",
        "/api/v1/tenant/connectors/registration-tokens",
        f"/api/v1/tenant/connectors/{uuid4()}",
    ):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Tenant administrator access required."
        )


def test_tenant_administrator_can_read_connector_inventories():
    client = TestClient(connector_app(administrator=True))
    assert client.get("/api/v1/tenant/connectors").status_code == 200
    assert (
        client.get("/api/v1/tenant/connectors/registration-tokens").status_code
        == 200
    )
