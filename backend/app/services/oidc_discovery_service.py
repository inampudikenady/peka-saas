import httpx
from pydantic import BaseModel


class OIDCDiscoveryDocument(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class OIDCDiscoveryService:
    def discover(self, issuer_url: str) -> OIDCDiscoveryDocument:
        issuer = issuer_url.rstrip("/")
        discovery_url = f"{issuer}/.well-known/openid-configuration"

        response = httpx.get(discovery_url, timeout=10)
        response.raise_for_status()

        return OIDCDiscoveryDocument.model_validate(response.json())
