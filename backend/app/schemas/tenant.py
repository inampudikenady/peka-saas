from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
