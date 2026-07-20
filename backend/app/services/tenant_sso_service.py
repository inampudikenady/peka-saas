import logging
from uuid import UUID

from app.models.tenant_sso_config import TenantSSOConfig
from app.core.url_builder import build_tenant_auth_callback_url
from app.repositories.tenant_repository import TenantRepository
from app.repositories.tenant_sso_repository import TenantSSORepository
from app.schemas.tenant_sso import TenantSSOConfigUpdate
from app.services.oidc_discovery_service import OIDCDiscoveryService

logger = logging.getLogger(__name__)


class TenantSSOService:
    def __init__(
        self,
        repository: TenantSSORepository,
        tenant_repository: TenantRepository,
        discovery_service: OIDCDiscoveryService,
    ) -> None:
        self.repository = repository
        self.tenant_repository = tenant_repository
        self.discovery_service = discovery_service

    def get(self, tenant_id: UUID) -> TenantSSOConfig | None:
        return self.repository.get_by_tenant_id(tenant_id)

    def upsert(
        self,
        tenant_id: UUID,
        payload: TenantSSOConfigUpdate,
    ) -> TenantSSOConfig:
        discovery = self.discovery_service.discover(payload.issuer_url)
        existing = self.repository.get_by_tenant_id(tenant_id)

        if (
            not payload.client_secret
            and (existing is None or not existing.client_secret_encrypted)
        ):
            raise ValueError("Client secret is required for initial SSO configuration.")

        tenant = self.tenant_repository.get_by_id(tenant_id)
        if tenant is None:
            raise ValueError(f"Tenant '{tenant_id}' was not found.")

        redirect_uri = build_tenant_auth_callback_url(
            slug=tenant.slug,
            hostname=tenant.subdomain,
        )

        try:
            if existing is None:
                result = TenantSSOConfig(
                    tenant_id=tenant_id,
                    provider=payload.provider,
                    issuer_url=discovery.issuer,
                    client_id=payload.client_id,
                    client_secret_encrypted=payload.client_secret,
                    authorization_endpoint=discovery.authorization_endpoint,
                    token_endpoint=discovery.token_endpoint,
                    jwks_uri=discovery.jwks_uri,
                    redirect_uri=redirect_uri,
                    scopes=payload.scopes,
                    enabled=payload.enabled,
                )
                result = self.repository.add(result)
            else:
                existing.provider = payload.provider
                existing.issuer_url = discovery.issuer
                existing.client_id = payload.client_id
                if payload.client_secret:
                    existing.client_secret_encrypted = payload.client_secret
                existing.authorization_endpoint = discovery.authorization_endpoint
                existing.token_endpoint = discovery.token_endpoint
                existing.jwks_uri = discovery.jwks_uri
                existing.redirect_uri = redirect_uri
                existing.scopes = payload.scopes
                existing.enabled = payload.enabled
                result = existing

            self.repository.commit()
            self.repository.refresh(result)

            logger.info("Updated SSO configuration for tenant %s", tenant_id)
            return result

        except Exception:
            self.repository.rollback()
            logger.exception("Failed to update SSO configuration for tenant %s", tenant_id)
            raise
