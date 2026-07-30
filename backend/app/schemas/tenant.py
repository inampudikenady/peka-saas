from datetime import datetime
from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.timezones import canonical_timezone
from app.models.tenant import TenantStatus
from app.models.tenant_user import TenantUserAuthSource


class TenantCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=100)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    display_name: str = Field(..., min_length=2, max_length=255)
    primary_domain: Optional[str] = Field(default=None, max_length=255)
    subdomain: Optional[str] = Field(default=None, max_length=255)
    tenant_url: Optional[str] = Field(default=None, max_length=500)
    timezone: str = Field(default="UTC", max_length=100)
    initial_admin_email: str = Field(..., max_length=255)
    initial_admin_full_name: str = Field(..., min_length=2, max_length=255)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        return canonical_timezone(value)


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    display_name: str
    status: TenantStatus
    primary_domain: Optional[str]
    subdomain: Optional[str]
    tenant_url: Optional[str]
    timezone: str
    created_at: datetime
    updated_at: datetime

    @field_validator("timezone")
    @classmethod
    def response_timezone_is_canonical(cls, value: str) -> str:
        return canonical_timezone(value)


class TenantCreateResponse(BaseModel):
    tenant: TenantResponse
    admin_setup_link: str


class TenantAdminInviteResponse(BaseModel):
    email: str
    full_name: str
    expires_at: datetime
    used_at: datetime | None
    status: str
    setup_link: str | None = None


class TenantPlatformSummary(BaseModel):
    sso_enabled: bool
    sso_redirect_uri: str | None
    local_admin_active: bool
    active_user_count: int
    administrator_count: int
    connector_count: int


class TenantUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=255)
    timezone: str | None = Field(default=None, max_length=100)

    @field_validator("timezone")
    @classmethod
    def update_timezone_must_be_iana(cls, value: str | None) -> str | None:
        return canonical_timezone(value) if value is not None else None


class TenantAdminInviteUpdate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=2, max_length=255)


class TenantAdministratorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    username: str | None
    is_active: bool
    last_login_at: datetime | None
    auth_source: TenantUserAuthSource


class TenantAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    tenant_slug: str
    tenant_display_name: str
    actor_username: str
    action: str
    changes: dict[str, Any]
    request_id: str | None
    created_at: datetime
