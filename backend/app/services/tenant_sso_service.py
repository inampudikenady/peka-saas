import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import OIDCConfigurationError
from app.core.url_builder import build_tenant_auth_callback_url
from app.models.tenant_sso_config import SSOProvider, TenantSSOConfig
from app.repositories.tenant_repository import TenantRepository
from app.repositories.tenant_sso_repository import TenantSSORepository
from app.schemas.tenant_sso import TenantSSOConfigUpdate, TenantSSOTestResponse
from app.services.oidc_discovery_service import (
    OIDCDiscoveryService,
    entra_issuer_url,
    entra_tenant_id_from_issuer,
    normalize_entra_tenant_id,
    normalize_issuer_url,
)
from app.services.oidc_secret_cipher import OIDCSecretCipher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OIDCRuntimeConfiguration:
    tenant_id: UUID
    provider: SSOProvider
    issuer_url: str
    client_id: str
    client_secret: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    redirect_uri: str
    scopes: str
    enabled: bool


class TenantSSOService:
    def __init__(
        self,
        repository: TenantSSORepository,
        tenant_repository: TenantRepository,
        discovery_service: OIDCDiscoveryService,
        secret_cipher: OIDCSecretCipher | None = None,
    ) -> None:
        self.repository = repository
        self.tenant_repository = tenant_repository
        self.discovery_service = discovery_service
        self.secret_cipher = secret_cipher or OIDCSecretCipher()

    def get(self, tenant_id: UUID) -> TenantSSOConfig | None:
        config = self.repository.get_by_tenant_id(tenant_id)
        if config is None:
            return None
        changed = False
        if config.client_secret_encrypted and not self.secret_cipher.is_encrypted(
            config.client_secret_encrypted
        ):
            config.client_secret_encrypted = self.secret_cipher.encrypt(
                config.client_secret_encrypted
            )
            changed = True
        if (
            config.provider == SSOProvider.MICROSOFT_ENTRA
            and not config.entra_tenant_id
        ):
            config.entra_tenant_id = entra_tenant_id_from_issuer(config.issuer_url)
            changed = bool(config.entra_tenant_id) or changed
        tenant = self.tenant_repository.get_by_id(tenant_id)
        if tenant is not None:
            redirect_uri = build_tenant_auth_callback_url(
                slug=tenant.slug,
                hostname=tenant.subdomain,
                tenant_url=tenant.tenant_url,
            )
            if config.redirect_uri != redirect_uri:
                config.redirect_uri = redirect_uri
                changed = True
        if changed:
            self.repository.commit()
            self.repository.refresh(config)
        return config

    def resolve_for_authentication(self, tenant_id: UUID) -> OIDCRuntimeConfiguration:
        config = self.get(tenant_id)
        if config is None or not config.enabled:
            raise OIDCConfigurationError("SSO is not configured for this tenant.")
        required = {
            "issuer URL": config.issuer_url,
            "client ID": config.client_id,
            "client secret": config.client_secret_encrypted,
            "redirect URI": config.redirect_uri,
        }
        missing = next((label for label, value in required.items() if not value), None)
        if missing:
            raise OIDCConfigurationError(f"OIDC {missing} is missing.")
        discovery = self.discovery_service.discover(config.issuer_url)
        return OIDCRuntimeConfiguration(
            tenant_id=tenant_id,
            provider=config.provider,
            issuer_url=normalize_issuer_url(config.issuer_url),
            client_id=config.client_id,
            client_secret=self.secret_cipher.decrypt(config.client_secret_encrypted),
            authorization_endpoint=discovery.authorization_endpoint,
            token_endpoint=discovery.token_endpoint,
            jwks_uri=discovery.jwks_uri,
            redirect_uri=config.redirect_uri,
            scopes="openid profile email",
            enabled=True,
        )

    def upsert(
        self,
        tenant_id: UUID,
        payload: TenantSSOConfigUpdate,
    ) -> TenantSSOConfig:
        existing = self.repository.get_by_tenant_id(tenant_id)
        if not payload.client_secret and (
            existing is None or not existing.client_secret_encrypted
        ):
            raise OIDCConfigurationError(
                "Client secret is required for initial SSO configuration."
            )

        tenant = self.tenant_repository.get_by_id(tenant_id)
        if tenant is None:
            raise OIDCConfigurationError("The tenant was not found.")

        if payload.provider == SSOProvider.MICROSOFT_ENTRA:
            assert payload.entra_tenant_id is not None
            entra_tenant_id = normalize_entra_tenant_id(payload.entra_tenant_id)
            issuer_url = entra_issuer_url(entra_tenant_id)
        else:
            entra_tenant_id = None
            assert payload.issuer_url is not None
            issuer_url = normalize_issuer_url(payload.issuer_url)

        redirect_uri = build_tenant_auth_callback_url(
            slug=tenant.slug,
            hostname=tenant.subdomain,
            tenant_url=tenant.tenant_url,
        )
        if payload.client_secret:
            encrypted_secret = self.secret_cipher.encrypt(payload.client_secret)
        else:
            assert existing is not None and existing.client_secret_encrypted
            encrypted_secret = (
                existing.client_secret_encrypted
                if self.secret_cipher.is_encrypted(existing.client_secret_encrypted)
                else self.secret_cipher.encrypt(existing.client_secret_encrypted)
            )

        try:
            if existing is None:
                result = self.repository.add(TenantSSOConfig(tenant_id=tenant_id))
            else:
                result = existing
            result.provider = payload.provider
            result.entra_tenant_id = entra_tenant_id
            result.issuer_url = issuer_url
            result.client_id = payload.client_id
            result.client_secret_encrypted = encrypted_secret
            # Endpoints are runtime-derived provider data. Clear any old cache;
            # saving tenant-owned credentials must not depend on IdP reachability.
            result.authorization_endpoint = None
            result.token_endpoint = None
            result.jwks_uri = None
            result.redirect_uri = redirect_uri
            result.scopes = "openid profile email"
            result.enabled = payload.enabled

            self.repository.commit()
            self.repository.refresh(result)
            logger.info(
                "Updated tenant SSO configuration",
                extra={
                    "tenant_id": str(tenant_id),
                    "provider": payload.provider.value,
                    "failure_stage": None,
                },
            )
            return result
        except Exception:
            self.repository.rollback()
            logger.exception(
                "Failed to update tenant SSO configuration",
                extra={
                    "tenant_id": str(tenant_id),
                    "provider": payload.provider.value,
                    "failure_stage": "persist_configuration",
                },
            )
            raise

    def test_configuration(self, tenant_id: UUID) -> TenantSSOTestResponse:
        config = self.get(tenant_id)
        if config is None:
            raise OIDCConfigurationError(
                "Save the SSO configuration before testing it."
            )
        required = {
            "issuer URL": config.issuer_url,
            "client ID": config.client_id,
            "client secret": config.client_secret_encrypted,
            "redirect URI": config.redirect_uri,
        }
        missing = next((label for label, value in required.items() if not value), None)
        if missing:
            raise OIDCConfigurationError(f"OIDC {missing} is missing.")

        discovery = self.discovery_service.discover(config.issuer_url)
        config.issuer_url = normalize_issuer_url(discovery.issuer)
        config.authorization_endpoint = discovery.authorization_endpoint
        config.token_endpoint = discovery.token_endpoint
        config.jwks_uri = discovery.jwks_uri
        try:
            self.repository.commit()
            self.repository.refresh(config)
        except Exception:
            self.repository.rollback()
            raise
        logger.info(
            "Tenant SSO discovery test succeeded",
            extra={"tenant_id": str(tenant_id), "provider": config.provider.value},
        )
        return TenantSSOTestResponse(
            success=True,
            issuer_url=config.issuer_url,
            authorization_endpoint=config.authorization_endpoint,
            token_endpoint=config.token_endpoint,
            jwks_uri=config.jwks_uri,
            message="OIDC discovery succeeded. The configuration is ready for login testing.",
        )
