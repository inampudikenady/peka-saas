from pydantic import BaseModel, Field

from app.models.tenant_sso_config import SSOProvider


class TenantSSOConfigUpdate(BaseModel):
    provider: SSOProvider = SSOProvider.GENERIC_OIDC
    issuer_url: str = Field(..., max_length=500)
    client_id: str = Field(..., max_length=255)
    client_secret: str = Field(..., min_length=1, max_length=1000)
    scopes: str = Field(default="openid profile email", max_length=500)
    enabled: bool = False


class TenantSSOConfigResponse(BaseModel):
    provider: SSOProvider
    issuer_url: str | None
    client_id: str | None
    authorization_endpoint: str | None
    token_endpoint: str | None
    jwks_uri: str | None
    redirect_uri: str | None
    scopes: str
    enabled: bool