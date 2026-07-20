from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import allow_platform_user, require_tenant_admin
from app.core.connector_security import hash_registration_token, verify_connector_secret
from app.db.base import Base
from app.models.connector import ConnectorEvent, ConnectorEventType, ConnectorRegistrationToken, ManagedConnectorStatus
from app.models.platform_admin import PlatformAdminRole
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.tenant_repository import TenantRepository
from app.schemas.connector_api import ConnectorHeartbeatRequest, ConnectorRegistrationRequest
from app.services.connector_service import ConnectorService, ConnectorServiceError
from app.services.connector_status_service import ConnectorStatusService


@pytest.fixture()
def lifecycle():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(slug="acme", name="Acme", display_name="Acme", status=TenantStatus.ACTIVE, timezone="UTC")
    other = Tenant(slug="other", name="Other", display_name="Other", status=TenantStatus.ACTIVE, timezone="UTC")
    db.add_all([tenant, other]); db.flush()
    admin = TenantUser(tenant_id=tenant.id, username="admin", email="admin@acme.test", full_name="Admin", auth_source=TenantUserAuthSource.LOCAL, password_hash="unused", is_active=True, role=TenantUserRole.TENANT_ADMIN)
    readonly = TenantUser(tenant_id=tenant.id, username="reader", email="reader@acme.test", full_name="Reader", auth_source=TenantUserAuthSource.LOCAL, password_hash="unused", is_active=True, role=TenantUserRole.TENANT_USER)
    db.add_all([admin, readonly]); db.commit()
    service = ConnectorService(ConnectorRepository(db), TenantRepository(db))
    yield db, service, tenant, other, admin, readonly
    db.close(); engine.dispose()


def registration_payload(raw: str, instance_id=None) -> ConnectorRegistrationRequest:
    return ConnectorRegistrationRequest(registration_token=raw, connector_name="acme-files", connector_version="1.2.3", environment="production", instance_id=instance_id or uuid4(), capabilities=["filesystem_documents"])


def heartbeat_payload(instance_id, *, unhealthy=0) -> ConnectorHeartbeatRequest:
    return ConnectorHeartbeatRequest.model_validate({
        "instance_id": str(instance_id), "connector_version": "1.2.4", "timestamp": datetime.now(UTC).isoformat(),
        "status": "healthy", "uptime_seconds": 12345,
        "sources": {"total": 1, "healthy": 0 if unhealthy else 1, "unhealthy": unhealthy, "disabled": 0},
        "capabilities": ["filesystem_documents"],
    })


def create_and_register(service, tenant, admin, instance_id=None):
    created = service.create_registration_token(tenant.id, admin, None)
    return created, service.register(registration_payload(created.registration_token, instance_id))


def test_token_is_hashed_single_use_and_raw_returned_once(lifecycle):
    db, service, tenant, _, admin, _ = lifecycle
    created = service.create_registration_token(tenant.id, admin, "acme-files")
    stored = db.scalar(select(ConnectorRegistrationToken).where(ConnectorRegistrationToken.id == created.id))
    assert stored.token_hash == hash_registration_token(created.registration_token)
    assert created.registration_token not in stored.token_hash
    assert "registration_token" not in service.list_registration_tokens(tenant.id)[0].model_dump()
    service.register(registration_payload(created.registration_token))
    with pytest.raises(ConnectorServiceError) as exc:
        service.register(registration_payload(created.registration_token))
    assert exc.value.status_code == 409


def test_expired_and_revoked_tokens_return_gone(lifecycle):
    db, service, tenant, _, admin, _ = lifecycle
    expired = service.create_registration_token(tenant.id, admin, None)
    stored = db.get(ConnectorRegistrationToken, expired.id); stored.expires_at = service.now() - timedelta(seconds=1); db.commit()
    with pytest.raises(ConnectorServiceError) as exc:
        service.register(registration_payload(expired.registration_token))
    assert exc.value.status_code == 410
    assert db.scalar(select(ConnectorEvent).where(ConnectorEvent.event_type == ConnectorEventType.REGISTRATION_TOKEN_EXPIRED))
    revoked = service.create_registration_token(tenant.id, admin, None)
    service.revoke_registration_token(tenant.id, revoked.id, admin)
    with pytest.raises(ConnectorServiceError) as exc:
        service.register(registration_payload(revoked.registration_token))
    assert exc.value.status_code == 410


def test_registration_hashes_secret_and_rejects_duplicate_instance(lifecycle):
    db, service, tenant, _, admin, _ = lifecycle
    instance_id = uuid4(); _, registered = create_and_register(service, tenant, admin, instance_id)
    connector = service.repository.get(tenant.id, registered.connector_id)
    assert registered.connector_secret not in connector.secret_hash
    assert verify_connector_secret(registered.connector_secret, connector.secret_hash)
    token = service.create_registration_token(tenant.id, admin, None)
    with pytest.raises(ConnectorServiceError) as exc:
        service.register(registration_payload(token.registration_token, instance_id))
    assert exc.value.status_code == 409
    assert db.get(ConnectorRegistrationToken, token.id).used_at is None


def test_heartbeat_authentication_source_health_and_recovery(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    _, registered = create_and_register(service, tenant, admin)
    connector = service.repository.get(tenant.id, registered.connector_id)
    response = service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(connector.instance_id))
    assert response.accepted is True
    assert connector.status == ManagedConnectorStatus.CONNECTED
    service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(connector.instance_id, unhealthy=1))
    assert connector.status == ManagedConnectorStatus.DEGRADED
    assert service.repository.recent_events(tenant.id, connector.id)[0].event_type in {ConnectorEventType.STATUS_CHANGED, ConnectorEventType.SOURCE_HEALTH_CHANGED}
    service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(connector.instance_id))
    assert connector.status == ManagedConnectorStatus.CONNECTED


def test_invalid_secret_header_and_instance_are_rejected(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    _, registered = create_and_register(service, tenant, admin)
    connector = service.repository.get(tenant.id, registered.connector_id)
    for header, secret, expected in [(str(connector.id), "wrong", 401), (str(uuid4()), registered.connector_secret, 401)]:
        with pytest.raises(ConnectorServiceError) as exc:
            service.heartbeat(connector.id, header, secret, heartbeat_payload(connector.instance_id))
        assert exc.value.status_code == expected
    with pytest.raises(ConnectorServiceError):
        service.heartbeat(connector.id, str(connector.id), "wrong-again", heartbeat_payload(connector.instance_id))
    assert connector.status == ManagedConnectorStatus.AUTHENTICATION_FAILED
    with pytest.raises(ConnectorServiceError) as exc:
        service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(uuid4()))
    assert exc.value.status_code == 409
    assert service.repository.recent_heartbeats(tenant.id, connector.id)[0].accepted is False


def test_tenant_isolation_and_retirement(lifecycle):
    _, service, tenant, other, admin, _ = lifecycle
    _, registered = create_and_register(service, tenant, admin)
    assert len(service.list_tenant_connectors(tenant.id)) == 1
    assert service.list_tenant_connectors(other.id) == []
    with pytest.raises(ConnectorServiceError) as exc:
        service.get_tenant_detail(other.id, registered.connector_id)
    assert exc.value.status_code == 404
    retired = service.retire(tenant.id, registered.connector_id, admin)
    assert retired.status == "retired"
    with pytest.raises(ConnectorServiceError) as exc:
        service.heartbeat(registered.connector_id, str(registered.connector_id), registered.connector_secret, heartbeat_payload(registered.connector_id))
    assert exc.value.status_code == 401


def test_status_thresholds_and_integration_recovery(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    _, registered = create_and_register(service, tenant, admin)
    connector = service.repository.get(tenant.id, registered.connector_id)
    start = datetime.now(UTC)
    service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(connector.instance_id))
    status = ConnectorStatusService()
    assert status.derive(connector, connector.last_heartbeat_at + timedelta(seconds=450)) == ManagedConnectorStatus.CONNECTED
    assert status.derive(connector, connector.last_heartbeat_at + timedelta(seconds=451)) == ManagedConnectorStatus.OUT_OF_SYNC
    assert status.derive(connector, connector.last_heartbeat_at + timedelta(seconds=1500)) == ManagedConnectorStatus.DISCONNECTED
    service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(connector.instance_id))
    assert connector.status == ManagedConnectorStatus.CONNECTED
    assert start <= connector.last_heartbeat_at


def test_role_policies_allow_reads_but_restrict_mutation(lifecycle):
    _, _, _, _, admin, readonly = lifecycle
    assert require_tenant_admin(admin) is admin
    with pytest.raises(HTTPException) as exc:
        require_tenant_admin(readonly)
    assert exc.value.status_code == 403
    platform_readonly = type("PlatformUser", (), {"role": PlatformAdminRole.PLATFORM_READONLY})()
    assert allow_platform_user(platform_readonly) is platform_readonly
