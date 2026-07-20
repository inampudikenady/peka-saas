from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.connector import (
    ConnectorCapability,
    ConnectorEvent,
    ConnectorHeartbeat,
    ConnectorRegistrationToken,
    ManagedConnector,
)
from app.models.tenant import Tenant


class ConnectorRepository:
    """All tenant-facing methods require a tenant id by construction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, entity):
        self.db.add(entity)
        self.db.flush()
        return entity

    def get_registration_token_for_update(self, token_hash: str) -> ConnectorRegistrationToken | None:
        return self.db.scalar(select(ConnectorRegistrationToken).where(ConnectorRegistrationToken.token_hash == token_hash).with_for_update())

    def get_registration_token(self, tenant_id: UUID, token_id: UUID) -> ConnectorRegistrationToken | None:
        return self.db.scalar(select(ConnectorRegistrationToken).where(ConnectorRegistrationToken.id == token_id, ConnectorRegistrationToken.tenant_id == tenant_id))

    def list_registration_tokens(self, tenant_id: UUID) -> list[ConnectorRegistrationToken]:
        return list(self.db.scalars(select(ConnectorRegistrationToken).where(ConnectorRegistrationToken.tenant_id == tenant_id).order_by(ConnectorRegistrationToken.created_at.desc())).all())

    def list_unrecorded_expired_tokens(self, now: datetime) -> list[ConnectorRegistrationToken]:
        return list(self.db.scalars(select(ConnectorRegistrationToken).where(
            ConnectorRegistrationToken.expires_at <= now,
            ConnectorRegistrationToken.used_at.is_(None),
            ConnectorRegistrationToken.revoked_at.is_(None),
            ConnectorRegistrationToken.expiration_event_recorded_at.is_(None),
        )).all())

    def get_active_by_instance(self, tenant_id: UUID, instance_id: UUID) -> ManagedConnector | None:
        return self.db.scalar(select(ManagedConnector).where(ManagedConnector.tenant_id == tenant_id, ManagedConnector.instance_id == instance_id, ManagedConnector.retired_at.is_(None)))

    def get(self, tenant_id: UUID, connector_id: UUID) -> ManagedConnector | None:
        return self.db.scalar(select(ManagedConnector).where(ManagedConnector.id == connector_id, ManagedConnector.tenant_id == tenant_id))

    def get_unscoped(self, connector_id: UUID) -> ManagedConnector | None:
        """Public secret authentication and platform inventory are the only callers."""
        return self.db.get(ManagedConnector, connector_id)

    def list_for_tenant(self, tenant_id: UUID) -> list[ManagedConnector]:
        return list(self.db.scalars(select(ManagedConnector).where(ManagedConnector.tenant_id == tenant_id).order_by(ManagedConnector.name, ManagedConnector.registered_at.desc())).all())

    def list_for_platform(self) -> list[tuple[ManagedConnector, Tenant]]:
        rows = self.db.execute(select(ManagedConnector, Tenant).join(Tenant, Tenant.id == ManagedConnector.tenant_id).order_by(Tenant.display_name, ManagedConnector.name)).all()
        return [(connector, tenant) for connector, tenant in rows]

    def list_all(self) -> list[ManagedConnector]:
        return list(self.db.scalars(select(ManagedConnector)).all())

    def replace_capabilities(self, connector: ManagedConnector, names: list[str], now: datetime) -> None:
        self.db.execute(delete(ConnectorCapability).where(ConnectorCapability.connector_id == connector.id))
        for name in names:
            self.db.add(ConnectorCapability(connector_id=connector.id, tenant_id=connector.tenant_id, name=name, last_reported_at=now))

    def list_capabilities(self, tenant_id: UUID, connector_id: UUID) -> list[str]:
        return list(self.db.scalars(select(ConnectorCapability.name).where(ConnectorCapability.tenant_id == tenant_id, ConnectorCapability.connector_id == connector_id).order_by(ConnectorCapability.name)).all())

    def recent_heartbeats(self, tenant_id: UUID, connector_id: UUID, limit: int = 50) -> list[ConnectorHeartbeat]:
        return list(self.db.scalars(select(ConnectorHeartbeat).where(ConnectorHeartbeat.tenant_id == tenant_id, ConnectorHeartbeat.connector_id == connector_id).order_by(ConnectorHeartbeat.received_at.desc()).limit(limit)).all())

    def recent_events(self, tenant_id: UUID, connector_id: UUID, limit: int = 100) -> list[ConnectorEvent]:
        return list(self.db.scalars(select(ConnectorEvent).where(ConnectorEvent.tenant_id == tenant_id, ConnectorEvent.connector_id == connector_id).order_by(ConnectorEvent.occurred_at.desc()).limit(limit)).all())

    def delete_heartbeats_before(self, cutoff: datetime) -> int:
        result = self.db.execute(delete(ConnectorHeartbeat).where(ConnectorHeartbeat.received_at < cutoff))
        return result.rowcount or 0

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
