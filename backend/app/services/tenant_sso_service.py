import logging

from app.models.tenant_sso_config import TenantSSOConfig
from app.repositories.tenant_sso_repository import TenantSSORepository

logger = logging.getLogger(__name__)


class TenantSSOService:
    def __init__(self, repository: TenantSSORepository) -> None:
        self.repository = repository

    def get(self, tenant_id):
        return self.repository.get_by_tenant_id(tenant_id)

    def upsert(self, config: TenantSSOConfig) -> TenantSSOConfig:
        existing = self.repository.get_by_tenant_id(config.tenant_id)

        try:
            if existing is None:
                result = self.repository.add(config)
            else:
                existing.provider = config.provider
                existing.issuer_url = config.issuer_url
                existing.client_id = config.client_id
                existing.client_secret_encrypted = config.client_secret_encrypted
                existing.authorization_endpoint = config.authorization_endpoint
                existing.token_endpoint = config.token_endpoint
                existing.jwks_uri = config.jwks_uri
                existing.redirect_uri = config.redirect_uri
                existing.scopes = config.scopes
                existing.enabled = config.enabled
                result = existing

            self.repository.commit()
            self.repository.refresh(result)

            logger.info("Updated SSO configuration for tenant %s", config.tenant_id)

            return result

        except Exception:
            self.repository.rollback()
            logger.exception(
                "Failed to update SSO configuration for tenant %s",
                config.tenant_id,
            )
            raise
