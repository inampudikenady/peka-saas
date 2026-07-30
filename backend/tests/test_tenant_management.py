from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.auth import require_platform_admin
from app.api.dependencies import get_tenant_service
from app.api.routes.platform import tenants as tenant_routes
from app.core.timezones import iana_timezone_catalog
from app.core.exceptions import TenantLifecycleError
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_admin_invite import TenantAdminInvite
from app.models.tenant_sso_config import SSOProvider
from app.schemas.tenant_sso import TenantSSOConfigUpdate
from app.schemas.tenant import TenantCreate, TenantResponse
from app.services.tenant_admin_invite_service import TenantAdminInviteService
from app.services.tenant_service import TenantService
from app.services.tenant_sso_service import TenantSSOService


def make_tenant(status=TenantStatus.ACTIVE):
    tenant = Tenant(
        slug="tuple",
        name="Tuple",
        display_name="Tuple",
        subdomain="tuple.peka.com",
        tenant_url="https://tuple.peka.com",
        timezone="UTC",
        status=status,
    )
    tenant.id = uuid4()
    tenant.created_at = datetime.now(UTC)
    tenant.updated_at = datetime.now(UTC)
    return tenant


class TenantRepositoryStub:
    def __init__(self, tenant):
        self.tenant = tenant
        self.deleted = False
        self.committed = False

    def get_by_slug(self, slug):
        return self.tenant if slug == self.tenant.slug else None

    def delete(self, tenant):
        self.deleted = True

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def refresh(self, tenant):
        pass


def tenant_service(tenant):
    repository = TenantRepositoryStub(tenant)
    registry = SimpleNamespace(remove_by_slug=lambda slug: setattr(registry, "removed", slug))
    manager = SimpleNamespace(registry=registry, add=lambda item: None)
    return TenantService(repository, manager, SimpleNamespace()), repository, registry


def test_active_tenant_cannot_be_deleted():
    service, repository, _ = tenant_service(make_tenant())
    with pytest.raises(TenantLifecycleError, match="Deactivate"):
        service.delete("tuple", "tuple")
    assert not repository.deleted


def test_suspended_tenant_delete_requires_confirmation_and_updates_registry():
    service, repository, registry = tenant_service(make_tenant(TenantStatus.SUSPENDED))
    with pytest.raises(TenantLifecycleError, match="confirmation"):
        service.delete("tuple", "wrong")
    service.delete("tuple", "tuple")
    assert repository.deleted and repository.committed
    assert registry.removed == "tuple"


def test_deactivate_and_reactivate_do_not_require_typed_confirmation():
    tenant = make_tenant()
    service, repository, _ = tenant_service(tenant)

    assert service.set_active("tuple", active=False).status == TenantStatus.SUSPENDED
    assert service.set_active("tuple", active=True).status == TenantStatus.ACTIVE
    assert repository.committed


def test_platform_readonly_cannot_call_tenant_lifecycle_endpoint():
    app = FastAPI()
    app.include_router(tenant_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_tenant_service] = lambda: SimpleNamespace()

    def reject_readonly():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access required.",
        )

    app.dependency_overrides[require_platform_admin] = reject_readonly
    response = TestClient(app).post("/api/v1/platform/tenants/tuple/deactivate")
    assert response.status_code == status.HTTP_403_FORBIDDEN


class InviteRepositoryStub:
    def __init__(self, invite):
        self.invite = invite
        self.added = None

    def get_latest_for_tenant(self, tenant_id):
        return self.invite

    def get_latest_unused_for_tenant(self, tenant_id):
        return self.invite if self.invite.used_at is None else None

    def add(self, invite):
        invite.id = uuid4()
        invite.created_at = datetime.now(UTC)
        self.added = invite
        return invite

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, invite):
        pass


def test_historic_invite_status_never_exposes_setup_link():
    tenant = make_tenant()
    invite = TenantAdminInvite(
        tenant_id=tenant.id,
        email="admin@example.com",
        full_name="Admin User",
        token_hash="hash",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    invite.id = uuid4()
    response = TenantAdminInviteService(InviteRepositoryStub(invite)).get_status(tenant)
    assert response is not None
    assert response.status == "pending"
    assert response.setup_link is None


def test_regeneration_expires_old_invite_and_returns_only_new_setup_link():
    tenant = make_tenant()
    old = TenantAdminInvite(
        tenant_id=tenant.id,
        email="admin@example.com",
        full_name="Admin User",
        token_hash="old-hash",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    old.id = uuid4()
    repository = InviteRepositoryStub(old)
    response = TenantAdminInviteService(repository).regenerate(tenant, uuid4())
    assert old.expires_at <= datetime.now(UTC)
    assert response.setup_link is not None
    assert "token=" in response.setup_link
    assert repository.added.token_hash not in response.setup_link


def test_blank_sso_secret_preserves_existing_value():
    tenant = make_tenant()
    config = SimpleNamespace(
        client_secret_encrypted="enc:stored-secret",
        provider=SSOProvider.MICROSOFT_ENTRA,
        entra_tenant_id=None,
        issuer_url="old",
        client_id="old",
        authorization_endpoint=None,
        token_endpoint=None,
        jwks_uri=None,
        redirect_uri=None,
        scopes="openid",
        enabled=False,
    )
    sso_repository = SimpleNamespace(
        get_by_tenant_id=lambda tenant_id: config,
        commit=lambda: None,
        refresh=lambda value: None,
        rollback=lambda: None,
    )
    tenant_repository = SimpleNamespace(get_by_id=lambda tenant_id: tenant)
    discovery = SimpleNamespace(
        discover=lambda issuer: SimpleNamespace(
            issuer=issuer,
            authorization_endpoint="authorize",
            token_endpoint="token",
            jwks_uri="jwks",
        )
    )
    cipher = SimpleNamespace(
        encrypt=lambda secret: f"enc:{secret}",
        decrypt=lambda secret: secret.removeprefix("enc:"),
        is_encrypted=lambda secret: secret.startswith("enc:"),
    )
    service = TenantSSOService(
        sso_repository, tenant_repository, discovery, cipher
    )
    service.upsert(
        tenant.id,
        TenantSSOConfigUpdate(
            provider=SSOProvider.MICROSOFT_ENTRA,
            entra_tenant_id="11111111-1111-4111-8111-111111111111",
            client_id="client",
            client_secret=None,
            enabled=True,
        ),
    )
    assert config.client_secret_encrypted == "enc:stored-secret"
    assert config.issuer_url == (
        "https://login.microsoftonline.com/"
        "11111111-1111-4111-8111-111111111111/v2.0"
    )
    # Save is local and deterministic; discovery is tested separately.
    assert config.authorization_endpoint is None
    assert config.token_endpoint is None
    assert config.jwks_uri is None


def test_tenant_creation_requires_an_iana_timezone():
    values = {
        "slug": "tuple",
        "name": "Tuple",
        "display_name": "Tuple",
        "initial_admin_email": "admin@example.com",
        "initial_admin_full_name": "Admin User",
    }
    assert TenantCreate(**values, timezone="Asia/Kolkata").timezone == "Asia/Kolkata"
    assert TenantCreate(**values, timezone="Asia/Calcutta").timezone == "Asia/Kolkata"
    with pytest.raises(ValueError, match="IANA"):
        TenantCreate(**values, timezone="India Standard Time")


def test_full_canonical_iana_timezone_catalog_is_available():
    catalog = iana_timezone_catalog()
    assert len(catalog) > 400
    assert "Asia/Kolkata" in catalog
    assert "Europe/London" in catalog
    assert "America/New_York" in catalog
    assert "Australia/Sydney" in catalog
    assert "Asia/Calcutta" not in catalog


def test_tenant_response_normalizes_deprecated_timezone_alias():
    tenant = make_tenant()
    tenant.timezone = "Asia/Calcutta"
    assert TenantResponse.model_validate(tenant).timezone == "Asia/Kolkata"
