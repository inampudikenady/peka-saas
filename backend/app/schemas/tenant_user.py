from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.tenant_user import TenantUserAuthSource, TenantUserRole


class TenantUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    username: str | None
    email: str
    full_name: str
    auth_source: TenantUserAuthSource
    role: TenantUserRole
    is_active: bool
    last_login_at: datetime | None


class TenantUserRoleUpdate(BaseModel):
    role: TenantUserRole


class TenantUserCreate(BaseModel):
    full_name: str
    email: str
    username: str
    role: TenantUserRole


class TenantUserInvitationResponse(BaseModel):
    user: TenantUserResponse
    setup_link: str
    expires_at: datetime
