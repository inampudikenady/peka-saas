from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.tenant_sso_config import SSOProvider


class TenantSSOConfigUpdate(BaseModel):
    provider: SSOProvider = SSOProvider.GENERIC_OIDC
    entra_tenant_id: str | None = Field(default=None, max_length=255)
    issuer_url: str | None = Field(default=None, max_length=500)
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str | None = Field(default=None, max_length=1000)
    enabled: bool = False

    @field_validator("client_id")
    @classmethod
    def client_id_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Client ID is required.")
        return normalized

    @field_validator("client_secret")
    @classmethod
    def blank_secret_keeps_existing(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value if value.strip() else None

    @model_validator(mode="after")
    def provider_fields_are_complete(self):
        if self.provider == SSOProvider.MICROSOFT_ENTRA:
            if not self.entra_tenant_id:
                raise ValueError("Microsoft Entra tenant ID is required.")
        elif not self.issuer_url:
            raise ValueError("Issuer URL is required for Generic OpenID Connect.")
        return self


class TenantSSOConfigResponse(BaseModel):
    provider: SSOProvider
    entra_tenant_id: str | None = None
    issuer_url: str | None
    client_id: str | None
    client_secret_configured: bool
    redirect_uri: str | None
    enabled: bool


class TenantSSOLoginOptions(BaseModel):
    provider: SSOProvider | None
    enabled: bool


class TenantSSOTestResponse(BaseModel):
    success: bool
    issuer_url: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    message: str
