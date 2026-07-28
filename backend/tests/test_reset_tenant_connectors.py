from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.connector import (
    ConnectorCapability,
    ConnectorEvent,
    ConnectorEventType,
    ConnectorHeartbeat,
    ConnectorRegistrationToken,
    ManagedConnector,
    ManagedConnectorStatus,
)
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.scripts.reset_tenant_connectors import (
    _confirmed,
    connector_data_counts,
    delete_connector_data,
    main,
    resolve_tenant,
)


def add_tenant(db: Session, slug: str) -> tuple[Tenant, TenantUser]:
    tenant = Tenant(
        slug=slug,
        name=slug.title(),
        display_name=slug.title(),
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    db.add(tenant)
    db.flush()
    user = TenantUser(
        tenant_id=tenant.id,
        username=f"{slug}-admin",
        email=f"admin@{slug}.test",
        full_name=f"{slug.title()} Admin",
        auth_source=TenantUserAuthSource.LOCAL,
        password_hash="unused",
        is_active=True,
        role=TenantUserRole.TENANT_ADMIN,
    )
    db.add(user)
    db.flush()
    return tenant, user


def add_connector_data(
    db: Session,
    tenant: Tenant,
    user: TenantUser,
    *,
    all_states: bool,
) -> None:
    now = datetime.now(UTC)
    token_states: tuple[dict[str, datetime], ...] = (
        {},
        {"used_at": now},
        {"expires_at": now - timedelta(minutes=1)},
        {"revoked_at": now},
    )
    tokens: list[ConnectorRegistrationToken] = []
    for index, overrides in enumerate(token_states):
        token = ConnectorRegistrationToken(
            tenant_id=tenant.id,
            token_hash=f"{tenant.slug}-{index}".ljust(64, "0"),
            expires_at=overrides.get("expires_at", now + timedelta(minutes=30)),
            used_at=overrides.get("used_at"),
            revoked_at=overrides.get("revoked_at"),
            created_by_user_id=user.id,
            intended_connector_name=f"Connector {index}",
        )
        db.add(token)
        tokens.append(token)
    db.flush()

    statuses = list(ManagedConnectorStatus) if all_states else [ManagedConnectorStatus.CONNECTED]
    for index, status in enumerate(statuses):
        connector = ManagedConnector(
            tenant_id=tenant.id,
            name=f"Connector {index}",
            instance_id=uuid4(),
            version="1.0.0",
            environment="test",
            status=status,
            secret_hash=f"unused-{tenant.slug}-{index}",
            registered_at=now,
            last_seen_at=now,
            heartbeat_interval_seconds=300,
            retired_at=now if status == ManagedConnectorStatus.RETIRED else None,
        )
        db.add(connector)
        db.flush()
        db.add(ConnectorCapability(
            connector_id=connector.id,
            tenant_id=tenant.id,
            name="filesystem_documents",
            last_reported_at=now,
        ))
        db.add(ConnectorHeartbeat(
            connector_id=connector.id,
            tenant_id=tenant.id,
            received_at=now,
            reported_at=now,
            version="1.0.0",
            reported_status="healthy",
            uptime_seconds=1,
            source_total=1,
            source_healthy=1,
            source_unhealthy=0,
            source_disabled=0,
            accepted=True,
        ))
        db.add(ConnectorEvent(
            tenant_id=tenant.id,
            connector_id=connector.id,
            registration_token_id=tokens[index % len(tokens)].id,
            event_type=ConnectorEventType.REGISTERED,
            occurred_at=now,
            actor_user_id=user.id,
            detail="Test event.",
        ))
    db.commit()


def test_cleanup_removes_only_selected_tenant_connector_data():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        target, target_user = add_tenant(db, "vitwo")
        other, other_user = add_tenant(db, "other")
        add_connector_data(db, target, target_user, all_states=True)
        add_connector_data(db, other, other_user, all_states=False)

        resolved = resolve_tenant(db, "vitwo")
        assert resolved is not None
        assert resolved.id == target.id
        before = connector_data_counts(db, target.id)
        assert before.managed_connectors == len(ManagedConnectorStatus)
        assert before.heartbeats == len(ManagedConnectorStatus)
        assert before.capabilities == len(ManagedConnectorStatus)
        assert before.connector_events == len(ManagedConnectorStatus)
        assert before.registration_tokens == 4
        tokens = list(db.scalars(
            select(ConnectorRegistrationToken).where(
                ConnectorRegistrationToken.tenant_id == target.id
            )
        ).all())
        comparison_now = datetime.now(UTC).replace(tzinfo=None)
        assert any(token.used_at is None and token.revoked_at is None and token.expires_at > comparison_now for token in tokens)
        assert any(token.used_at is not None for token in tokens)
        assert any(token.revoked_at is not None for token in tokens)
        assert any(token.expires_at < comparison_now for token in tokens)

        after = delete_connector_data(db, target.id)

        assert after.all_zero()
        assert connector_data_counts(db, target.id).all_zero()
        assert not connector_data_counts(db, other.id).all_zero()
        assert db.get(Tenant, target.id) is not None
        assert db.get(Tenant, other.id) is not None
        assert db.scalar(
            select(func.count(TenantUser.id)).where(TenantUser.tenant_id == target.id)
        ) == 1
        assert db.scalar(
            select(func.count(TenantUser.id)).where(TenantUser.tenant_id == other.id)
        ) == 1
    finally:
        db.close()
        engine.dispose()


def test_confirmation_requires_exact_tenant_phrase():
    assert _confirmed("vitwo", lambda _prompt: "DELETE vitwo") is True
    assert _confirmed("vitwo", lambda _prompt: "yes") is False


def test_production_requires_additional_override(monkeypatch):
    monkeypatch.setattr("app.scripts.reset_tenant_connectors.settings.environment", "production")
    monkeypatch.setattr(
        "app.scripts.reset_tenant_connectors.SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )

    assert main(["--tenant", "vitwo", "--yes"]) == 2
