"""Versioned shared contract between PEKA SaaS and the PEKA Connector.

Keep this module backward compatible with the connector client's typed models.
Timestamps are timezone-aware ISO-8601 values and are serialized as UTC.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_serializer,
    field_validator,
    model_validator,
)


ConnectorCapabilityName = Literal[
    "filesystem_documents", "operational_tools", "local_knowledge"
]
ConnectorName = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[^\x00-\x1f]+$")
]
ConnectorVersion = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
]
ConnectorEnvironment = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
]


class ConnectorAPIModel(BaseModel):
    """Base contract that always emits connector API timestamps as UTC."""

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_utc_datetimes(self, value: Any) -> Any:
        if not isinstance(value, datetime):
            return value
        normalized = (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )
        return normalized.isoformat()


class ConnectorRegistrationErrorCode(str, Enum):
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_USED = "TOKEN_USED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    TOKEN_HASH_MISMATCH = "TOKEN_HASH_MISMATCH"
    INSTANCE_ALREADY_REGISTERED = "INSTANCE_ALREADY_REGISTERED"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    TENANT_INACTIVE = "TENANT_INACTIVE"
    CONNECTOR_LIMIT_REACHED = "CONNECTOR_LIMIT_REACHED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REGISTRATION_NOT_PERMITTED = "REGISTRATION_NOT_PERMITTED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ConnectorRegistrationErrorResponse(ConnectorAPIModel):
    """Credential-safe error returned by connector registration."""

    code: ConnectorRegistrationErrorCode
    message: str


class ConnectorRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registration_token: str = Field(min_length=20, max_length=512)
    connector_name: ConnectorName = Field(
        validation_alias=AliasChoices("connector_name", "name")
    )
    connector_version: ConnectorVersion = Field(
        validation_alias=AliasChoices("connector_version", "version")
    )
    environment: ConnectorEnvironment
    instance_id: UUID
    capabilities: list[ConnectorCapabilityName] = Field(
        default_factory=list, max_length=32
    )

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


class ConnectorRegistrationResponse(ConnectorAPIModel):
    _registration_token_id: UUID | None = PrivateAttr(default=None)

    connector_id: UUID
    tenant_id: UUID
    connector_secret: str
    heartbeat_interval_seconds: int
    registered_at: datetime
    configuration_version: Literal["1"] = "1"
    tenant_timezone: str


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


class LocalKnowledgeStoreSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded", "unavailable"]
    documents: int = Field(ge=0)
    indexed_chunks: int = Field(ge=0)
    last_index_activity: datetime | None = None

    @field_validator("last_index_activity")
    @classmethod
    def activity_is_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("last_index_activity must include a UTC offset")
        return value


class ConnectorHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: UUID
    connector_name: ConnectorName | None = Field(
        default=None,
        validation_alias=AliasChoices("connector_name", "name"),
    )
    connector_version: ConnectorVersion = Field(
        validation_alias=AliasChoices("connector_version", "version")
    )
    environment: ConnectorEnvironment | None = None
    timestamp: datetime
    status: Literal["healthy"]
    uptime_seconds: int = Field(ge=0)
    sources: ConnectorSourceSummary
    capabilities: list[ConnectorCapabilityName] = Field(
        default_factory=list, max_length=32
    )
    local_knowledge_store: LocalKnowledgeStoreSummary | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a UTC offset")
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must be UTC")
        return value


class ConnectorHeartbeatResponse(ConnectorAPIModel):
    accepted: Literal[True] = True
    server_time: datetime
    next_heartbeat_seconds: int
    configuration_version: Literal["1"] = "1"
    tenant_timezone: str


class RegistrationTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrationTokenResponse(ConnectorAPIModel):
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


class ConnectorSummaryResponse(ConnectorAPIModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    tenant_name: str | None = None
    tenant_slug: str | None = None
    tenant_timezone: str | None = None
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
    local_knowledge_store_status: str | None
    knowledge_document_count: int
    knowledge_indexed_chunk_count: int
    last_knowledge_index_activity_at: datetime | None
    retired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConnectorHeartbeatHistoryResponse(ConnectorAPIModel):
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
    local_knowledge_store_status: str | None
    knowledge_document_count: int
    knowledge_indexed_chunk_count: int
    last_knowledge_index_activity_at: datetime | None
    accepted: bool


class ConnectorEventResponse(ConnectorAPIModel):
    model_config = ConfigDict(from_attributes=True)
    event_type: str
    occurred_at: datetime
    detail: str | None


class ConnectorDetailResponse(ConnectorSummaryResponse):
    capabilities: list[str]
    recent_heartbeats: list[ConnectorHeartbeatHistoryResponse]
    recent_events: list[ConnectorEventResponse]
