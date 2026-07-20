from pydantic import BaseModel, Field

from app.models.tenant_user import TenantUserAuthSource, TenantUserRole


class TenantAdminSetupRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=12)


class TenantLocalLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class TenantAuthResult(BaseModel):
    authenticated: bool = True


class TenantMeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    auth_source: TenantUserAuthSource
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    role: TenantUserRole
    username: str | None
    is_active: bool
    last_login_at: str | None


class TenantChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=12)
