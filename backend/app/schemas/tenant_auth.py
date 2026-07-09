from pydantic import BaseModel, Field


class TenantAdminSetupRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=12)


class TenantAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
