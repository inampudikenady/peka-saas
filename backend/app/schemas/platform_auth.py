from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.platform_admin import PlatformAdminRole


class PlatformLoginRequest(BaseModel):
    username: str
    password: str


class PlatformTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PlatformUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    email: str
    full_name: str
    role: PlatformAdminRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=255)
    full_name: str = Field(min_length=2, max_length=255)
    role: PlatformAdminRole


class PlatformUserUpdate(BaseModel):
    email: str = Field(max_length=255)
    full_name: str = Field(min_length=2, max_length=255)
    role: PlatformAdminRole


class PlatformInvitationResponse(BaseModel):
    user: PlatformUserResponse
    setup_link: str
    expires_at: datetime


class PlatformPasswordResetRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=12)


class PlatformChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)
