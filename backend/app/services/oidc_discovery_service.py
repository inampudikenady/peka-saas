import re
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.core.exceptions import OIDCConfigurationError


ENTRA_ISSUER_PATTERN = re.compile(
    r"^https://login\.microsoftonline\.com/"
    r"(?P<tenant_id>[0-9a-fA-F-]{36})/v2\.0$"
)


def normalize_entra_tenant_id(value: str) -> str:
    if value != value.strip() or any(character.isspace() for character in value):
        raise OIDCConfigurationError(
            "Microsoft Entra tenant ID must not contain whitespace."
        )
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise OIDCConfigurationError(
            "Microsoft Entra tenant ID must be a valid directory UUID."
        ) from exc


def entra_issuer_url(tenant_id: str) -> str:
    normalized = normalize_entra_tenant_id(tenant_id)
    return f"https://login.microsoftonline.com/{normalized}/v2.0"


def entra_tenant_id_from_issuer(issuer_url: str | None) -> str | None:
    if not issuer_url:
        return None
    match = ENTRA_ISSUER_PATTERN.fullmatch(issuer_url.rstrip("/"))
    if match is None:
        return None
    try:
        return normalize_entra_tenant_id(match.group("tenant_id"))
    except OIDCConfigurationError:
        return None


def normalize_issuer_url(value: str) -> str:
    if value != value.strip() or any(character.isspace() for character in value):
        raise OIDCConfigurationError("OIDC issuer URL must not contain whitespace.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise OIDCConfigurationError(
            "OIDC issuer URL must be an HTTPS URL without credentials, query, or fragment."
        )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), path, "", ""))


class OIDCDiscoveryDocument(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class OIDCDiscoveryService:
    def discover(self, issuer_url: str) -> OIDCDiscoveryDocument:
        issuer = normalize_issuer_url(issuer_url)
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        try:
            response = httpx.get(discovery_url, timeout=10)
            response.raise_for_status()
            document = OIDCDiscoveryDocument.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise OIDCConfigurationError(
                "OIDC discovery failed for the configured issuer."
            ) from exc
        if normalize_issuer_url(document.issuer) != issuer:
            raise OIDCConfigurationError(
                "OIDC discovery returned an issuer that does not match the configuration."
            )
        return document
