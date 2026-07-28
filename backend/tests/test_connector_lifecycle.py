from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
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
from app.schemas.connector_api import ConnectorHeartbeatRequest, ConnectorRegistrationRequest, RegistrationTokenCreate
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


def heartbeat_payload(instance_id, *, unhealthy=0, name=None, environment=None) -> ConnectorHeartbeatRequest:
    payload = {
        "instance_id": str(instance_id), "connector_version": "1.2.4", "timestamp": datetime.now(UTC).isoformat(),
        "status": "healthy", "uptime_seconds": 12345,
        "sources": {"total": 1, "healthy": 0 if unhealthy else 1, "unhealthy": unhealthy, "disabled": 0},
        "capabilities": ["filesystem_documents"],
    }
    if name is not None:
        payload["name"] = name
    if environment is not None:
        payload["environment"] = environment
    return ConnectorHeartbeatRequest.model_validate(payload)


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
    assert exc.value.status_code == 410


def test_token_without_name_and_historical_intended_name_are_readable(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    assert RegistrationTokenCreate.model_validate({}).model_dump() == {}
    created = service.create_registration_token(tenant.id, admin, None)
    historical = service.create_registration_token(tenant.id, admin, "Legacy intended name")

    tokens = service.list_registration_tokens(tenant.id)

    assert next(token for token in tokens if token.id == created.id).intended_connector_name is None
    assert next(token for token in tokens if token.id == historical.id).intended_connector_name == "Legacy intended name"
    registered = service.register(registration_payload(historical.registration_token))
    assert service.repository.get(tenant.id, registered.connector_id).name == "acme-files"


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


def test_heartbeat_updates_connector_owned_metadata_and_read_models(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    _, registered = create_and_register(service, tenant, admin)
    connector = service.repository.get(tenant.id, registered.connector_id)
    original_identity = (connector.id, connector.instance_id, connector.tenant_id, connector.secret_hash)

    service.heartbeat(
        connector.id,
        str(connector.id),
        registered.connector_secret,
        heartbeat_payload(
            connector.instance_id,
            name="VITWO Production Connector",
            environment="production-eu",
        ),
    )

    assert connector.name == "VITWO Production Connector"
    assert connector.environment == "production-eu"
    assert connector.version == "1.2.4"
    assert (connector.id, connector.instance_id, connector.tenant_id, connector.secret_hash) == original_identity
    assert service.list_tenant_connectors(tenant.id)[0].name == "VITWO Production Connector"
    assert service.get_tenant_detail(tenant.id, connector.id).name == "VITWO Production Connector"


def test_heartbeat_cannot_modify_another_connector_or_identity_fields(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    _, first = create_and_register(service, tenant, admin)
    _, second = create_and_register(service, tenant, admin)
    first_connector = service.repository.get(tenant.id, first.connector_id)
    second_connector = service.repository.get(tenant.id, second.connector_id)

    with pytest.raises(ConnectorServiceError):
        service.heartbeat(
            second_connector.id,
            str(second_connector.id),
            first.connector_secret,
            heartbeat_payload(second_connector.instance_id, name="Unauthorized rename"),
        )
    assert second_connector.name == "acme-files"

    with pytest.raises(ValidationError):
        ConnectorHeartbeatRequest.model_validate({
            **heartbeat_payload(first_connector.instance_id).model_dump(mode="json"),
            "tenant_id": str(uuid4()),
            "connector_id": str(second_connector.id),
        })
    assert first_connector.tenant_id == tenant.id
    assert first_connector.instance_id != second_connector.instance_id


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
    original_name = connector.name
    with pytest.raises(ConnectorServiceError) as exc:
        service.heartbeat(connector.id, str(connector.id), registered.connector_secret, heartbeat_payload(uuid4(), name="Rejected rename"))
    assert exc.value.status_code == 409
    assert connector.name == original_name
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


def test_connector_inventory_hides_only_retired_by_default(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    _, disconnected = create_and_register(service, tenant, admin)
    _, degraded = create_and_register(service, tenant, admin)
    degraded_connector = service.repository.get(tenant.id, degraded.connector_id)
    service.heartbeat(
        degraded_connector.id,
        str(degraded_connector.id),
        degraded.connector_secret,
        heartbeat_payload(degraded_connector.instance_id, unhealthy=1),
    )
    _, retired = create_and_register(service, tenant, admin)
    service.retire(tenant.id, retired.connector_id, admin)

    tenant_default = service.list_tenant_connectors(tenant.id)
    tenant_with_retired = service.list_tenant_connectors(tenant.id, include_retired=True)
    platform_default = service.list_platform_connectors()
    platform_with_retired = service.list_platform_connectors(include_retired=True)

    assert {item.id for item in tenant_default} == {disconnected.connector_id, degraded.connector_id}
    assert {item.status for item in tenant_default} == {"disconnected", "degraded"}
    assert {item.id for item in tenant_with_retired} == {
        disconnected.connector_id,
        degraded.connector_id,
        retired.connector_id,
    }
    assert {item.id for item in platform_default} == {disconnected.connector_id, degraded.connector_id}
    assert {item.id for item in platform_with_retired} == {
        disconnected.connector_id,
        degraded.connector_id,
        retired.connector_id,
    }


def test_registration_token_inventory_hides_inactive_by_default(lifecycle):
    db, service, tenant, _, admin, _ = lifecycle
    active = service.create_registration_token(tenant.id, admin, None)
    used = service.create_registration_token(tenant.id, admin, None)
    service.register(registration_payload(used.registration_token))
    expired = service.create_registration_token(tenant.id, admin, None)
    expired_record = db.get(ConnectorRegistrationToken, expired.id)
    expired_record.expires_at = service.now() - timedelta(seconds=1)
    revoked = service.create_registration_token(tenant.id, admin, None)
    service.revoke_registration_token(tenant.id, revoked.id, admin)
    db.commit()

    default = service.list_registration_tokens(tenant.id)
    with_inactive = service.list_registration_tokens(tenant.id, include_inactive=True)

    assert [token.id for token in default] == [active.id]
    assert {token.status for token in with_inactive} == {"active", "used", "expired", "revoked"}


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


def test_connector_api_timestamps_are_timezone_aware_utc(lifecycle):
    _, service, tenant, _, admin, _ = lifecycle
    created, registered = create_and_register(service, tenant, admin)
    connector = service.repository.get(tenant.id, registered.connector_id)
    service.heartbeat(
        connector.id,
        str(connector.id),
        registered.connector_secret,
        heartbeat_payload(connector.instance_id),
    )

    payloads = [
        registered.model_dump(mode="json"),
        created.model_dump(mode="json"),
        service.list_tenant_connectors(tenant.id)[0].model_dump(mode="json"),
        service.get_tenant_detail(tenant.id, connector.id).model_dump(mode="json"),
    ]
    timestamp_fields = {
        "registered_at", "last_heartbeat_at", "last_seen_at", "created_at",
        "updated_at", "expires_at", "received_at", "reported_at", "occurred_at",
    }
    values = []
    for payload in payloads:
        values.extend(value for key, value in payload.items() if key in timestamp_fields and value is not None)
        for collection in ("recent_heartbeats", "recent_events"):
            values.extend(
                value
                for item in payload.get(collection, [])
                for key, value in item.items()
                if key in timestamp_fields and value is not None
            )
    assert values
    assert all(datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() == timedelta(0) for value in values)


def test_role_policies_allow_reads_but_restrict_mutation(lifecycle):
    _, _, _, _, admin, readonly = lifecycle
    assert require_tenant_admin(admin) is admin
    with pytest.raises(HTTPException) as exc:
        require_tenant_admin(readonly)
    assert exc.value.status_code == 403
    platform_readonly = type("PlatformUser", (), {"role": PlatformAdminRole.PLATFORM_READONLY})()
    assert allow_platform_user(platform_readonly) is platform_readonly
