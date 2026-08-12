from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.models.platform_admin import PlatformAdmin
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_audit_event import TenantAuditEvent
from app.models.tenant_user import (
    DevelopmentEmail,
    TenantPasswordResetToken,
    TenantUser,
    TenantUserAuthSource,
    TenantUserRole,
)
from app.services.tenant_password_reset_service import (
    TenantPasswordResetError,
    TenantPasswordResetService,
)


@pytest.fixture()
def reset_context():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(
        slug="resetco",
        name="Reset Co",
        display_name="Reset Co",
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    local = TenantUser(
        tenant_id=tenant.id,
        username="local-admin",
        email="local@example.test",
        full_name="Local Admin",
        auth_source=TenantUserAuthSource.LOCAL,
        role=TenantUserRole.TENANT_ADMIN,
        password_hash=hash_password("Original-password-2026!"),
        is_active=True,
        failed_login_attempts=5,
        locked=True,
    )
    sso = TenantUser(
        tenant_id=tenant.id,
        email="sso@example.test",
        full_name="SSO Admin",
        auth_source=TenantUserAuthSource.SSO,
        role=TenantUserRole.TENANT_ADMIN,
        is_active=True,
    )
    db.add(tenant)
    db.flush()
    local.tenant_id = tenant.id
    sso.tenant_id = tenant.id
    db.add_all([local, sso])
    db.commit()
    yield db, tenant, local, sso
    db.close()
    engine.dispose()


def test_tenant_reset_is_hashed_single_use_unlocks_and_preserves_role(
    reset_context,
) -> None:
    db, tenant, local, _sso = reset_context
    service = TenantPasswordResetService(db)
    assert service.request_for_email(tenant, "LOCAL@example.test") is None

    reset = db.scalar(select(TenantPasswordResetToken))
    email = db.scalar(select(DevelopmentEmail))
    assert reset is not None and email is not None
    raw_token = parse_qs(urlsplit(email.action_url).query)["token"][0]
    assert raw_token not in reset.token_hash
    assert len(reset.token_hash) == 64

    service.reset(tenant, raw_token, "Replacement-password-2026!")
    db.refresh(local)
    assert verify_password("Replacement-password-2026!", local.password_hash)
    assert local.locked is False
    assert local.failed_login_attempts == 0
    assert local.role == TenantUserRole.TENANT_ADMIN
    with pytest.raises(TenantPasswordResetError, match="invalid or has expired"):
        service.reset(tenant, raw_token, "Another-password-2026!")
    assert db.scalar(
        select(func.count()).select_from(TenantAuditEvent).where(
            TenantAuditEvent.action == "tenant_password_reset_completed"
        )
    ) == 1


def test_sso_forgot_password_is_neutral_and_creates_no_token(reset_context) -> None:
    db, tenant, _local, _sso = reset_context
    TenantPasswordResetService(db).request_for_email(tenant, "sso@example.test")
    assert db.scalar(select(func.count()).select_from(TenantPasswordResetToken)) == 0
    assert db.scalar(select(func.count()).select_from(DevelopmentEmail)) == 0


def test_platform_admin_reset_uses_same_outbox_and_audits_actor(reset_context) -> None:
    db, tenant, local, _sso = reset_context
    actor = PlatformAdmin(
        username="platform-admin",
        email="platform@example.test",
        full_name="Platform Admin",
        password_hash=hash_password("Platform-password-2026!"),
    )
    db.add(actor)
    db.commit()
    TenantPasswordResetService(db).request_by_platform_admin(
        tenant, local.id, actor
    )
    event = db.scalar(
        select(TenantAuditEvent).where(
            TenantAuditEvent.action == "tenant_password_reset_requested"
        )
    )
    assert event is not None
    assert event.actor_platform_admin_id == actor.id
    assert event.changes["affected_user_id"] == str(local.id)
    assert db.scalar(select(func.count()).select_from(DevelopmentEmail)) == 1
