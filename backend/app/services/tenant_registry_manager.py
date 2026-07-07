import logging

from sqlalchemy.orm import Session

from app.core.tenant_definition import TenantDefinition
from app.core.tenant_registry import TenantRegistry
from app.models.tenant import TenantStatus
from app.repositories.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class TenantRegistryManager:
    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry

    def load(self, db: Session) -> None:
        repository = TenantRepository(db)
        tenants = repository.list_active()

        self.registry.clear()

        for tenant in tenants:
            if tenant.subdomain is None:
                continue

            definition = TenantDefinition(
                tenant_id=tenant.id,
                slug=tenant.slug,
                hostname=tenant.subdomain,
                enabled=tenant.status == TenantStatus.ACTIVE,
            )
            self.registry.add(definition)

        logger.info("Loaded %s tenants into tenant registry", self.registry.count())
