from datetime import datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tenant import TenantStatus


class TenantCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=100)
    name: str = Field(..., min_length=2, max_length=255)
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
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone ID") from exc
        return value


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
