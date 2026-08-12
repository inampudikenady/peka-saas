from typing import Any
import logging

import httpx
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.exceptions import OIDCAuthenticationError, OIDCConfigurationError
from app.core.identity import normalize_email
from app.core.logging import request_id_ctx
from app.models.tenant_sso_config import SSOProvider
from app.services.tenant_sso_service import OIDCRuntimeConfiguration


logger = logging.getLogger(__name__)


class OIDCUserIdentity(BaseModel):
    oid: str | None = None
    sub: str | None = None
    email: str
    issuer: str
    provider: SSOProvider
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None

    @property
    def subject(self) -> str:
        subject = self.oid or self.sub
        if (
            subject is None
        ):  # guarded during extraction; defensive for direct construction
            raise ValueError("OIDC identity does not contain a subject.")
        return subject


class OIDCAuthenticationService:
    def authenticate(
        self,
        config: OIDCRuntimeConfiguration,
        code: str,
        expected_nonce: str,
        redirect_uri: str,
        code_verifier: str | None,
    ) -> OIDCUserIdentity:
        if not config.token_endpoint:
            raise OIDCConfigurationError("OIDC token endpoint is missing.")

        if not config.jwks_uri:
            raise OIDCConfigurationError("OIDC JWKS URI is missing.")

        if not config.client_id:
            raise OIDCConfigurationError("OIDC client ID is missing.")

        if not config.client_secret:
            raise OIDCConfigurationError("OIDC client secret is missing.")

        if not redirect_uri:
            raise OIDCConfigurationError("OIDC redirect URI is missing.")

        if not config.issuer_url:
            raise OIDCConfigurationError("OIDC issuer URL is missing.")

        try:
            token_request = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": redirect_uri,
            }
            if code_verifier:
                token_request["code_verifier"] = code_verifier
            token_response = httpx.post(
                config.token_endpoint,
                data=token_request,
                timeout=15,
            )
            token_response.raise_for_status()
            token_data: dict[str, Any] = token_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "OIDC authorization code exchange failed",
                extra={
                    "tenant_id": str(config.tenant_id),
                    "provider": config.provider.value,
                    "failure_stage": "token_exchange",
                    "provider_http_status": (
                        exc.response.status_code
                        if isinstance(exc, httpx.HTTPStatusError)
                        else None
                    ),
                    "request_id": request_id_ctx.get(),
                },
            )
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
            logger.warning(
                "OIDC signing key validation failed",
                extra={
                    "tenant_id": str(config.tenant_id),
                    "provider": config.provider.value,
                    "failure_stage": "jwks",
                    "provider_http_status": (
                        exc.response.status_code
                        if isinstance(exc, httpx.HTTPStatusError)
                        else None
                    ),
                    "request_id": request_id_ctx.get(),
                },
            )
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
            logger.warning(
                "OIDC ID token validation failed",
                extra={
                    "tenant_id": str(config.tenant_id),
                    "provider": config.provider.value,
                    "failure_stage": "id_token_validation",
                    "request_id": request_id_ctx.get(),
                },
            )
            raise OIDCAuthenticationError("OIDC ID token validation failed.") from exc

        if claims.get("nonce") != expected_nonce:
            raise OIDCAuthenticationError("OIDC nonce validation failed.")

        email = claims.get("email") or claims.get("preferred_username")

        if not email:
            raise OIDCAuthenticationError(
                "OIDC identity does not contain an email address."
            )

        oid = claims.get("oid")
        sub = claims.get("sub")
        if not oid and not sub:
            raise OIDCAuthenticationError("OIDC identity does not contain a subject.")

        return OIDCUserIdentity(
            oid=oid,
            sub=sub,
            email=normalize_email(email),
            issuer=config.issuer_url,
            provider=config.provider,
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
