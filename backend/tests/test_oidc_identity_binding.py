from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import OIDCUserAuthorizationError
from app.core.identity import normalize_email
from app.models.tenant_sso_config import SSOProvider
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_user import (
    TenantUser,
    TenantUserAuthSource,
    TenantUserRole,
)
from app.repositories.tenant_user_repository import TenantUserRepository
from app.services.oidc_authentication_service import OIDCUserIdentity
from app.services.oidc_user_service import OIDCUserService


ISSUER = "https://login.microsoftonline.com/11111111-1111-4111-8111-111111111111/v2.0"


def identity(*, oid="current-oid", sub="legacy-sub", email="user@example.com"):
    return OIDCUserIdentity(
        oid=oid,
        sub=sub,
        email=email,
        issuer=ISSUER,
        provider=SSOProvider.MICROSOFT_ENTRA,
        display_name="Test User",
    )


def user(
    tenant_id,
    *,
    subject,
    email="user@example.com",
    active=True,
    locked=False,
    auth_source=TenantUserAuthSource.SSO,
):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email=email,
        full_name="Existing User",
        external_subject=subject,
        is_active=active,
        locked=locked,
        auth_source=auth_source,
        role=TenantUserRole.TENANT_USER,
        last_login_at=None,
    )


class FakeRepository:
    def __init__(
        self,
        users=(),
        *,
        conditional_update_succeeds=True,
        simulate_concurrent_migration=False,
    ):
        self.users = list(users)
        self.conditional_update_succeeds = conditional_update_succeeds
        self.simulate_concurrent_migration = simulate_concurrent_migration
        self.conditional_updates = []
        self.commits = 0
        self.rollbacks = 0

    def get_by_tenant_and_external_subject(self, tenant_id, subject):
        return next(
            (
                item
                for item in self.users
                if item.tenant_id == tenant_id and item.external_subject == subject
            ),
            None,
        )

    def get_by_tenant_and_email(self, tenant_id, email):
        normalized = normalize_email(email)
        return next(
            (
                item
                for item in self.users
                if item.tenant_id == tenant_id
                and normalize_email(item.email) == normalized
            ),
            None,
        )

    def update_external_subject_if_matches(
        self, tenant_id, user_id, expected_old_subject, new_subject
    ):
        self.conditional_updates.append(
            (tenant_id, user_id, expected_old_subject, new_subject)
        )
        if self.simulate_concurrent_migration:
            matched = next(item for item in self.users if item.id == user_id)
            matched.external_subject = new_subject
            return False
        if not self.conditional_update_succeeds:
            return False
        matched = next(
            (
                item
                for item in self.users
                if item.tenant_id == tenant_id
                and item.id == user_id
                and item.external_subject == expected_old_subject
            ),
            None,
        )
        if matched is None:
            return False
        matched.external_subject = new_subject
        return True

    def add(self, value):
        if value.id is None:
            value.id = uuid4()
        self.users.append(value)
        return value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, value):
        return None


def test_existing_current_oid_user_logs_in():
    tenant_id = uuid4()
    existing = user(tenant_id, subject="current-oid")
    repository = FakeRepository([existing])

    result = OIDCUserService(repository).provision(tenant_id, identity())

    assert result is existing
    assert repository.conditional_updates == []
    assert repository.commits == 1


def test_legacy_sub_is_conditionally_migrated_to_oid(caplog):
    tenant_id = uuid4()
    existing = user(tenant_id, subject="legacy-sub")
    repository = FakeRepository([existing])

    with caplog.at_level("INFO"):
        result = OIDCUserService(repository).provision(
            tenant_id, identity(), tenant_slug="acme"
        )

    assert result is existing
    assert existing.external_subject == "current-oid"
    assert repository.conditional_updates == [
        (tenant_id, existing.id, "legacy-sub", "current-oid")
    ]
    assert "oidc_legacy_subject_migrated" in caplog.text


def test_legacy_migration_is_scoped_to_resolved_tenant():
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = user(tenant_a, subject="legacy-sub")
    user_b = user(tenant_b, subject="legacy-sub")
    repository = FakeRepository([user_a, user_b])

    result = OIDCUserService(repository).provision(tenant_a, identity())

    assert result is user_a
    assert user_a.external_subject == "current-oid"
    assert user_b.external_subject == "legacy-sub"


def test_same_entra_identity_can_exist_in_two_peka_tenants():
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = user(tenant_a, subject="current-oid")
    user_b = user(tenant_b, subject="current-oid")
    repository = FakeRepository([user_a, user_b])
    service = OIDCUserService(repository)

    assert service.provision(tenant_a, identity()) is user_a
    assert service.provision(tenant_b, identity()) is user_b


def test_email_match_with_unrelated_subject_is_rejected():
    tenant_id = uuid4()
    existing = user(tenant_id, subject="unrelated-subject")
    repository = FakeRepository([existing])

    with pytest.raises(OIDCUserAuthorizationError):
        OIDCUserService(repository).provision(tenant_id, identity())

    assert existing.external_subject == "unrelated-subject"
    assert repository.conditional_updates == []


def test_legacy_migration_requires_exact_validated_sub():
    tenant_id = uuid4()
    existing = user(tenant_id, subject="different-legacy-sub")
    repository = FakeRepository([existing])

    with pytest.raises(OIDCUserAuthorizationError):
        OIDCUserService(repository).provision(tenant_id, identity())

    assert existing.external_subject == "different-legacy-sub"


def test_failed_conditional_update_never_overwrites_identity():
    tenant_id = uuid4()
    existing = user(tenant_id, subject="legacy-sub")
    repository = FakeRepository([existing], conditional_update_succeeds=False)

    with pytest.raises(OIDCUserAuthorizationError):
        OIDCUserService(repository).provision(tenant_id, identity())

    assert existing.external_subject == "legacy-sub"
    assert repository.rollbacks == 1


def test_concurrent_migration_of_same_user_is_accepted():
    tenant_id = uuid4()
    existing = user(tenant_id, subject="legacy-sub")
    repository = FakeRepository(
        [existing], simulate_concurrent_migration=True
    )

    result = OIDCUserService(repository).provision(tenant_id, identity())

    assert result is existing
    assert existing.external_subject == "current-oid"
    assert repository.rollbacks == 1


def test_legacy_subject_on_non_sso_user_is_not_migrated():
    tenant_id = uuid4()
    existing = user(
        tenant_id,
        subject="legacy-sub",
        auth_source=TenantUserAuthSource.LOCAL,
    )
    repository = FakeRepository([existing])

    with pytest.raises(OIDCUserAuthorizationError):
        OIDCUserService(repository).provision(tenant_id, identity())

    assert existing.external_subject == "legacy-sub"
    assert repository.conditional_updates == []


def test_repository_conditional_update_requires_tenant_user_and_old_subject():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Tenant.__table__.create(engine)
    TenantUser.__table__.create(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(
        slug="acme",
        name="Acme",
        display_name="Acme",
        status=TenantStatus.ACTIVE,
    )
    db.add(tenant)
    db.flush()
    existing = TenantUser(
        tenant_id=tenant.id,
        username=None,
        email=" User@Example.COM ",
        full_name="User",
        auth_source=TenantUserAuthSource.SSO,
        password_hash=None,
        external_subject="legacy-sub",
        is_active=True,
        locked=False,
        role=TenantUserRole.TENANT_USER,
    )
    db.add(existing)
    db.commit()
    repository = TenantUserRepository(db)

    assert repository.get_by_tenant_and_email(tenant.id, "user@example.com") is existing
    assert not repository.update_external_subject_if_matches(
        uuid4(), existing.id, "legacy-sub", "attacker-oid"
    )
    assert not repository.update_external_subject_if_matches(
        tenant.id, existing.id, "wrong-old-sub", "attacker-oid"
    )
    assert repository.update_external_subject_if_matches(
        tenant.id, existing.id, "legacy-sub", "current-oid"
    )
    db.commit()
    db.refresh(existing)
    assert existing.external_subject == "current-oid"


@pytest.mark.parametrize(
    ("active", "locked"),
    [(False, False), (True, True)],
)
def test_inactive_and_locked_users_are_rejected_before_commit(active, locked):
    tenant_id = uuid4()
    existing = user(
        tenant_id,
        subject="current-oid",
        active=active,
        locked=locked,
    )
    repository = FakeRepository([existing])

    with pytest.raises(OIDCUserAuthorizationError):
        OIDCUserService(repository).provision(tenant_id, identity())

    assert repository.commits == 0


def test_new_user_uses_oid_and_normalized_email():
    tenant_id = uuid4()
    repository = FakeRepository()

    created = OIDCUserService(repository).provision(
        tenant_id,
        identity(email="  User@Example.COM  "),
    )

    assert created.external_subject == "current-oid"
    assert created.email == "user@example.com"


def test_new_user_falls_back_to_sub_without_oid():
    tenant_id = uuid4()
    repository = FakeRepository()

    created = OIDCUserService(repository).provision(
        tenant_id,
        identity(oid=None, sub="only-sub"),
    )

    assert created.external_subject == "only-sub"


def test_safe_logs_do_not_include_identity_or_credentials(caplog):
    tenant_id = uuid4()
    existing = user(tenant_id, subject="legacy-secret-sub")
    repository = FakeRepository([existing])
    sensitive_values = (
        "private@example.com",
        "validated-secret-oid",
        "legacy-secret-sub",
        "authorization-code",
        "id-token",
        "client-secret",
        "cookie-value",
    )

    with caplog.at_level("INFO"):
        OIDCUserService(repository).provision(
            tenant_id,
            identity(
                oid="validated-secret-oid",
                sub="legacy-secret-sub",
                email="private@example.com",
            ),
        )

    assert all(value not in caplog.text for value in sensitive_values)
