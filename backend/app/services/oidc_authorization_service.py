from urllib.parse import urlencode

from app.models.tenant_sso_config import TenantSSOConfig


class OIDCAuthorizationService:
    def build_authorization_url(
        self,
        config: TenantSSOConfig,
        state: str,
        nonce: str,
    ) -> str:
        query = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "scope": config.scopes,
                "state": state,
                "nonce": nonce,
            }
        )

        return f"{config.authorization_endpoint}?{query}"
