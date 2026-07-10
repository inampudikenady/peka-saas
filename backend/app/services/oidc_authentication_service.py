from typing import Any

import httpx
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.exceptions import OIDCAuthenticationError, OIDCConfigurationError
from app.models.tenant_sso_config import TenantSSOConfig


class OIDCUserIdentity(BaseModel):
    subject: str
    email: str
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None


class OIDCAuthenticationService:
    def authenticate(
        self,
        config: TenantSSOConfig,
        code: str,
        expected_nonce: str,
    ) -> OIDCUserIdentity:
        if not config.token_endpoint:
            raise OIDCConfigurationError("OIDC token endpoint is missing.")

        if not config.jwks_uri:
            raise OIDCConfigurationError("OIDC JWKS URI is missing.")

        if not config.client_id:
            raise OIDCConfigurationError("OIDC client ID is missing.")

        if not config.client_secret_encrypted:
            raise OIDCConfigurationError("OIDC client secret is missing.")

        if not config.redirect_uri:
            raise OIDCConfigurationError("OIDC redirect URI is missing.")

        if not config.issuer_url:
            raise OIDCConfigurationError("OIDC issuer URL is missing.")

        try:
            token_response = httpx.post(
                config.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": config.client_id,
                    "client_secret": config.client_secret_encrypted,
                    "redirect_uri": config.redirect_uri,
                },
                timeout=15,
            )
            token_response.raise_for_status()
            token_data: dict[str, Any] = token_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCAuthenticationError(
                "OIDC authorization code exchange failed."
            ) from exc

        id_token = token_data.get("id_token")

        if not id_token:
            raise OIDCAuthenticationError("OIDC provider did not return an ID token.")

        try:
            jwks_response = httpx.get(config.jwks_uri, timeout=15)
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
            token_header = jwt.get_unverified_header(id_token)
            signing_key = self._find_signing_key(jwks, token_header.get("kid"))
        except (httpx.HTTPError, ValueError, JWTError) as exc:
            raise OIDCAuthenticationError(
                "OIDC signing keys could not be validated."
            ) from exc

        try:
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=["RS256"],
                audience=config.client_id,
                issuer=config.issuer_url,
                options={"verify_at_hash": False},
            )
        except JWTError as exc:
            raise OIDCAuthenticationError("OIDC ID token validation failed.") from exc

        if claims.get("nonce") != expected_nonce:
            raise OIDCAuthenticationError("OIDC nonce validation failed.")

        email = claims.get("email") or claims.get("preferred_username")

        if not email:
            raise OIDCAuthenticationError(
                "OIDC identity does not contain an email address."
            )

        subject = claims.get("sub")
        if not subject:
            raise OIDCAuthenticationError("OIDC identity does not contain a subject.")

        return OIDCUserIdentity(
            subject=subject,
            email=email.lower(),
            display_name=claims.get("name"),
            given_name=claims.get("given_name"),
            family_name=claims.get("family_name"),
        )

    @staticmethod
    def _find_signing_key(
        jwks: dict[str, Any],
        key_id: str | None,
    ) -> dict[str, Any]:
        for key in jwks.get("keys", []):
            if key.get("kid") == key_id:
                return key

        raise OIDCAuthenticationError("OIDC signing key was not found.")
