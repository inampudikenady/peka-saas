from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import TenantLifecycleError
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_admin_invite import TenantAdminInvite
from app.models.tenant_sso_config import SSOProvider
from app.schemas.tenant_sso import TenantSSOConfigUpdate
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


def tenant_service(tenant):
    repository = TenantRepositoryStub(tenant)
    registry = SimpleNamespace(remove_by_slug=lambda slug: setattr(registry, "removed", slug))
    manager = SimpleNamespace(registry=registry)
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
        client_secret_encrypted="stored-secret",
        provider=SSOProvider.ENTRA_ID,
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
    service = TenantSSOService(sso_repository, tenant_repository, discovery)
    service.upsert(
        tenant.id,
        TenantSSOConfigUpdate(
            provider=SSOProvider.ENTRA_ID,
            issuer_url="https://issuer.example",
            client_id="client",
            client_secret=None,
            enabled=True,
        ),
    )
    assert config.client_secret_encrypted == "stored-secret"
