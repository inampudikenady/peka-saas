import logging

from sqlalchemy.orm import Session

from app.core.tenant_definition import TenantDefinition
from app.core.tenant_registry import TenantRegistry
from app.models.tenant import Tenant, TenantStatus
from app.repositories.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class TenantRegistryManager:
    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry

    def add(self, tenant: Tenant) -> None:
        definition = TenantDefinition(
            tenant_id=tenant.id,
            slug=tenant.slug,
            hostname=tenant.subdomain or "",
            enabled=tenant.status == TenantStatus.ACTIVE,
        )
        self.registry.add(definition)
        logger.info("Added tenant '%s' to tenant registry", tenant.slug)

    def load(self, db: Session) -> None:
        repository = TenantRepository(db)
        tenants = repository.list_active()

        self.registry.clear()

        for tenant in tenants:
            self.add(tenant)

        logger.info("Loaded %s tenants into tenant registry", self.registry.count())
