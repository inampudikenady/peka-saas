from urllib.parse import urlencode

from app.services.tenant_sso_service import OIDCRuntimeConfiguration


class OIDCAuthorizationService:
    def build_authorization_url(
        self,
        config: OIDCRuntimeConfiguration,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        query = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "scope": config.scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if "?" in config.authorization_endpoint else "?"
        return f"{config.authorization_endpoint}{separator}{query}"
