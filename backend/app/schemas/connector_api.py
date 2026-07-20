"""Versioned shared contract between PEKA SaaS and the PEKA Connector.

Keep this module backward compatible with the connector client's typed models.
Timestamps are timezone-aware ISO-8601 values and are serialized as UTC.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ConnectorCapabilityName = Literal["filesystem_documents"]


class ConnectorRegistrationRequest(BaseModel):
    registration_token: str = Field(min_length=20, max_length=512)
    connector_name: str = Field(min_length=1, max_length=255, pattern=r"^[^\x00-\x1f]+$")
    connector_version: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
    environment: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
    instance_id: UUID
    capabilities: list[ConnectorCapabilityName] = Field(default_factory=list, max_length=32)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


class ConnectorRegistrationResponse(BaseModel):
    connector_id: UUID
    tenant_id: UUID
    connector_secret: str
    heartbeat_interval_seconds: int
    registered_at: datetime


class ConnectorSourceSummary(BaseModel):
    total: int = Field(ge=0)
    healthy: int = Field(ge=0)
    unhealthy: int = Field(ge=0)
    disabled: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "ConnectorSourceSummary":
        if self.healthy + self.unhealthy + self.disabled != self.total:
            raise ValueError("source counts must add up to total")
        return self


class ConnectorHeartbeatRequest(BaseModel):
    instance_id: UUID
    connector_version: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
    timestamp: datetime
    status: Literal["healthy"]
    uptime_seconds: int = Field(ge=0)
    sources: ConnectorSourceSummary
    capabilities: list[ConnectorCapabilityName] = Field(default_factory=list, max_length=32)

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a UTC offset")
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must be UTC")
        return value


class ConnectorHeartbeatResponse(BaseModel):
    accepted: Literal[True] = True
    server_time: datetime
    next_heartbeat_seconds: int


class RegistrationTokenCreate(BaseModel):
    intended_connector_name: str | None = Field(default=None, min_length=1, max_length=255)


class RegistrationTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    expires_at: datetime
    used_at: datetime | None
    created_by_user_id: UUID | None
    created_at: datetime
    revoked_at: datetime | None
    intended_connector_name: str | None
    status: Literal["active", "used", "expired", "revoked"]


class RegistrationTokenCreatedResponse(RegistrationTokenResponse):
    registration_token: str


class ConnectorSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    tenant_name: str | None = None
    tenant_slug: str | None = None
    name: str
    instance_id: UUID
    version: str
    environment: str
    status: str
    registered_at: datetime
    last_heartbeat_at: datetime | None
    last_seen_at: datetime | None
    heartbeat_interval_seconds: int
    source_total: int
    source_healthy: int
    source_unhealthy: int
    source_disabled: int
    retired_at: datetime | None


class ConnectorHeartbeatHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    received_at: datetime
    reported_at: datetime
    version: str
    reported_status: str
    uptime_seconds: int
    source_total: int
    source_healthy: int
    source_unhealthy: int
    source_disabled: int
    accepted: bool


class ConnectorEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_type: str
    occurred_at: datetime
    detail: str | None


class ConnectorDetailResponse(ConnectorSummaryResponse):
    capabilities: list[str]
    recent_heartbeats: list[ConnectorHeartbeatHistoryResponse]
    recent_events: list[ConnectorEventResponse]
