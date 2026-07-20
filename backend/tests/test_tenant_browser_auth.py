from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_oidc_authentication_service,
    get_oidc_user_service,
    get_tenant_account_activation_service,
    get_tenant_local_authentication_service,
    get_tenant_oidc_auth_session_service,
    get_tenant_sso_service,
)
from app.api.routes.tenant.auth import router as auth_router
from app.api.routes.tenant.security import router as security_router
from app.api.tenant_context import get_current_tenant_context
from app.core.config import settings
from app.core.security import create_access_token, create_tenant_access_token
from app.core.tenant_context import TenantContext
from app.core.tenant_definition import TenantDefinition
from app.core.tenant_session import tenant_cookie_path
from app.db.session import get_db
from app.models.tenant_sso_config import SSOProvider
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole


def make_context():
    definition = TenantDefinition(uuid4(), "vitwo", "vitwo.peka.com", True)
    return TenantContext(
        tenant_id=definition.tenant_id,
        slug=definition.slug,
        hostname=definition.hostname,
        definition=definition,
    )


def make_user(context, *, local=True, active=True):
    user = TenantUser(
        tenant_id=context.tenant_id,
        username="admin_vitwo" if local else None,
        email="admin@example.com",
        full_name="Tenant Admin",
        auth_source=(TenantUserAuthSource.LOCAL if local else TenantUserAuthSource.SSO),
        password_hash="hash" if local else None,
        is_active=active,
        role=(TenantUserRole.TENANT_ADMIN if local else TenantUserRole.TENANT_USER),
    )
    user.id = uuid4()
    return user


class FakeDB:
    def __init__(self, user):
        self.user = user

    def get(self, model, entity_id):
        return self.user if self.user and self.user.id == entity_id else None


class FakeSSOService:
    config = SimpleNamespace(
        provider=SSOProvider.ENTRA_ID,
        issuer_url="https://issuer.example",
        client_id="client-id",
        authorization_endpoint="https://issuer.example/authorize",
        token_endpoint="https://issuer.example/token",
        jwks_uri="https://issuer.example/keys",
        redirect_uri="https://vitwo.peka.com/callback",
        scopes="openid profile email",
        enabled=True,
    )

    def get(self, tenant_id):
        return self.config

    def upsert(self, tenant_id, payload):
        return self.config


def build_app(context, user=None):
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(security_router, prefix="/api/v1")
    app.dependency_overrides[get_current_tenant_context] = lambda: context
    app.dependency_overrides[get_db] = lambda: FakeDB(user)
    return app


@contextmanager
def tenant_mode(mode):
    previous = settings.tenant_url_mode
    settings.tenant_url_mode = mode
    try:
        yield
    finally:
        settings.tenant_url_mode = previous


def test_tenant_cookie_set_after_local_login():
    context = make_context()
    user = make_user(context)
    app = build_app(context)
    app.dependency_overrides[get_tenant_local_authentication_service] = lambda: (
        SimpleNamespace(authenticate=lambda **kwargs: user)
    )
    response = TestClient(app, base_url="https://testserver").post(
        "/api/v1/tenant/auth/local-login",
        json={"username": "admin_vitwo", "password": "secret"},
    )
    assert response.status_code == 200
    assert "peka_tenant_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "access_token" not in response.json()


def test_tenant_cookie_set_after_activation():
    context = make_context()
    user = make_user(context)
    app = build_app(context)
    app.dependency_overrides[get_tenant_account_activation_service] = lambda: (
        SimpleNamespace(activate=lambda **kwargs: user)
    )
    response = TestClient(app, base_url="https://testserver").post(
        "/api/v1/tenant/auth/activate",
        json={"token": "invite", "password": "long-enough-password"},
    )
    assert response.status_code == 200
    assert "peka_tenant_session=" in response.headers["set-cookie"]
    assert "access_token" not in response.json()


def test_callback_redirects_and_sets_cookie():
    context = make_context()
    user = make_user(context, local=False)
    app = build_app(context)
    auth_session = SimpleNamespace(nonce="nonce")
    app.dependency_overrides[get_tenant_sso_service] = lambda: FakeSSOService()
    app.dependency_overrides[get_tenant_oidc_auth_session_service] = lambda: (
        SimpleNamespace(validate=lambda **kwargs: auth_session, consume=lambda session: None)
    )
    app.dependency_overrides[get_oidc_authentication_service] = lambda: (
        SimpleNamespace(authenticate=lambda **kwargs: SimpleNamespace())
    )
    app.dependency_overrides[get_oidc_user_service] = lambda: (
        SimpleNamespace(provision=lambda **kwargs: user)
    )
    with tenant_mode("path"):
        response = TestClient(app, base_url="https://testserver").get(
            "/api/v1/tenant/auth/callback?code=code&state=state",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/t/vitwo/ai"
    assert "peka_tenant_session=" in response.headers["set-cookie"]


def test_me_succeeds_with_valid_cookie():
    context = make_context()
    user = make_user(context)
    app = build_app(context, user)
    token = create_tenant_access_token(user.id, user.username, context.tenant_id)
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(settings.tenant_session_cookie_name, token)
    response = client.get("/api/v1/tenant/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_me_rejects_platform_token():
    context = make_context()
    user = make_user(context)
    app = build_app(context, user)
    token = create_access_token(user.id, user.username)
    response = TestClient(app).get(
        "/api/v1/tenant/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_me_rejects_tenant_mismatch():
    context = make_context()
    user = make_user(context)
    app = build_app(context, user)
    token = create_tenant_access_token(user.id, user.username, uuid4())
    response = TestClient(app).get(
        "/api/v1/tenant/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_inactive_user_rejected():
    context = make_context()
    user = make_user(context, active=False)
    app = build_app(context, user)
    token = create_tenant_access_token(user.id, user.username, context.tenant_id)
    response = TestClient(app).get(
        "/api/v1/tenant/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_sso_routes_reject_unauthenticated_users():
    context = make_context()
    response = TestClient(build_app(context)).get(
        "/api/v1/tenant/admin/security/sso"
    )
    assert response.status_code == 401


def test_sso_routes_reject_non_admin_sso_users():
    context = make_context()
    user = make_user(context, local=False)
    app = build_app(context, user)
    token = create_tenant_access_token(user.id, user.email, context.tenant_id)
    response = TestClient(app).get(
        "/api/v1/tenant/admin/security/sso",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_bootstrap_local_admin_can_manage_sso():
    context = make_context()
    user = make_user(context)
    app = build_app(context, user)
    app.dependency_overrides[get_tenant_sso_service] = lambda: FakeSSOService()
    token = create_tenant_access_token(user.id, user.username, context.tenant_id)
    response = TestClient(app).get(
        "/api/v1/tenant/admin/security/sso",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "client_secret" not in response.json()
    assert "client_secret_encrypted" not in response.json()

    update_response = TestClient(app).put(
        "/api/v1/tenant/admin/security/sso",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "entra_id",
            "issuer_url": "https://issuer.example",
            "client_id": "client-id",
            "client_secret": "new-secret",
            "enabled": True,
        },
    )
    assert update_response.status_code == 200
    assert "client_secret" not in update_response.json()


def test_logout_clears_cookie():
    context = make_context()
    response = TestClient(build_app(context)).post("/api/v1/tenant/auth/logout")
    assert response.status_code == 204
    assert "peka_tenant_session=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_path_mode_cookie_path():
    with tenant_mode("path"):
        assert tenant_cookie_path("vitwo") == "/t/vitwo"


def test_subdomain_mode_cookie_path():
    with tenant_mode("subdomain"):
        assert tenant_cookie_path("vitwo") == "/"
