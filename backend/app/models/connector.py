"""Persistence models for customer-managed PEKA connectors.

Raw registration tokens and connector secrets are deliberately not represented
by any column in this module. Only their hashes cross the persistence boundary.
"""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class ManagedConnectorStatus(str, enum.Enum):
    CONNECTED = "connected"
    IN_SYNC = "in_sync"
    DEGRADED = "degraded"
    OUT_OF_SYNC = "out_of_sync"
    DISCONNECTED = "disconnected"
    AUTHENTICATION_FAILED = "authentication_failed"
    RETIRED = "retired"


class ConnectorEventType(str, enum.Enum):
    REGISTRATION_TOKEN_GENERATED = "registration_token_generated"
    REGISTRATION_TOKEN_REVOKED = "registration_token_revoked"
    REGISTRATION_TOKEN_USED = "registration_token_used"
    REGISTRATION_TOKEN_EXPIRED = "registration_token_expired"
    REGISTRATION_TOKEN_FAILED = "registration_token_failed"
    REGISTERED = "registered"
    HEARTBEAT_RECEIVED = "heartbeat_received"
    SOURCE_HEALTH_CHANGED = "source_health_changed"
    STATUS_CHANGED = "status_changed"
    AUTHENTICATION_FAILURE = "authentication_failure"
    RETIRED = "retired"


class ManagedConnector(Entity):
    __tablename__ = "managed_connectors"
    __table_args__ = (
        CheckConstraint("heartbeat_interval_seconds > 0", name="ck_managed_connectors_heartbeat_interval"),
        CheckConstraint("source_total >= 0 AND source_healthy >= 0 AND source_unhealthy >= 0 AND source_disabled >= 0", name="ck_managed_connectors_source_counts"),
        Index("ix_managed_connectors_tenant_status", "tenant_id", "status"),
        Index(
            "uq_managed_connectors_active_tenant_instance",
            "tenant_id",
            "instance_id",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    instance_id: Mapped[UUID] = mapped_column(nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ManagedConnectorStatus] = mapped_column(Enum(ManagedConnectorStatus, name="managed_connector_status"), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    source_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_healthy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_unhealthy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_missed_heartbeats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authentication_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorRegistrationToken(Entity):
    __tablename__ = "connector_registration_tokens"
    __table_args__ = (Index("ix_connector_registration_tokens_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intended_connector_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expiration_event_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorHeartbeat(Entity):
    __tablename__ = "connector_heartbeats"
    __table_args__ = (Index("ix_connector_heartbeats_connector_received", "connector_id", "received_at"),)

    connector_id: Mapped[UUID] = mapped_column(ForeignKey("managed_connectors.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    reported_status: Mapped[str] = mapped_column(String(50), nullable=False)
    uptime_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    source_total: Mapped[int] = mapped_column(Integer, nullable=False)
    source_healthy: Mapped[int] = mapped_column(Integer, nullable=False)
    source_unhealthy: Mapped[int] = mapped_column(Integer, nullable=False)
    source_disabled: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ConnectorCapability(Entity):
    __tablename__ = "connector_capabilities"
    __table_args__ = (UniqueConstraint("connector_id", "name", name="uq_connector_capabilities_connector_name"),)

    connector_id: Mapped[UUID] = mapped_column(ForeignKey("managed_connectors.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConnectorEvent(Entity):
    __tablename__ = "connector_events"
    __table_args__ = (Index("ix_connector_events_connector_occurred", "connector_id", "occurred_at"), Index("ix_connector_events_tenant_occurred", "tenant_id", "occurred_at"))

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    connector_id: Mapped[UUID | None] = mapped_column(ForeignKey("managed_connectors.id", ondelete="CASCADE"), nullable=True, index=True)
    registration_token_id: Mapped[UUID | None] = mapped_column(ForeignKey("connector_registration_tokens.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[ConnectorEventType] = mapped_column(Enum(ConnectorEventType, name="connector_event_type"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
