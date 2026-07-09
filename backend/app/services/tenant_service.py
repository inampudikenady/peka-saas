import logging

from app.core.exceptions import (
    TenantAlreadyExistsError,
    TenantDomainAlreadyExistsError,
    TenantNotFoundError,
)
from app.core.url_builder import build_platform_hostname, build_tenant_url
from app.models.tenant import Tenant
from app.repositories.tenant_repository import TenantRepository
from app.schemas.tenant import TenantCreate, TenantCreateResponse
from app.services.tenant_registry_manager import TenantRegistryManager
from app.services.tenant_bootstrap_service import TenantBootstrapService

logger = logging.getLogger(__name__)


class TenantService:
    def __init__(
        self,
        repository: TenantRepository,
        registry_manager: TenantRegistryManager,
        bootstrap_service: TenantBootstrapService,
    ) -> None:
        self.repository = repository
        self.registry_manager = registry_manager
        self.bootstrap_service = bootstrap_service

    def _build_tenant_endpoints(
        self,
        slug: str,
        requested_subdomain: str | None = None,
    ) -> tuple[str, str]:
        subdomain = requested_subdomain or build_platform_hostname(slug)
        tenant_url = build_tenant_url(slug=slug, hostname=subdomain)
        return subdomain, tenant_url

    def create(self, tenant: TenantCreate) -> TenantCreateResponse:
        logger.info("Creating tenant '%s'", tenant.slug)
        if self.repository.exists_by_slug(tenant.slug):
            raise TenantAlreadyExistsError(f"Tenant '{tenant.slug}' already exists.")

        if tenant.primary_domain and self.repository.exists_by_domain(
            tenant.primary_domain
        ):
            raise TenantDomainAlreadyExistsError(
                f"Primary domain '{tenant.primary_domain}' is already in use."
            )

        subdomain, tenant_url = self._build_tenant_endpoints(
            tenant.slug,
            tenant.subdomain,
        )

        entity = Tenant(
            slug=tenant.slug,
            name=tenant.name,
            display_name=tenant.display_name,
            primary_domain=tenant.primary_domain,
            subdomain=subdomain,
            tenant_url=tenant.tenant_url or tenant_url,
            timezone=tenant.timezone,
        )

        try:
            created_tenant = self.repository.add(entity)
            bootstrap_result = self.bootstrap_service.bootstrap(
                tenant=created_tenant,
                admin_email=tenant.initial_admin_email,
                admin_full_name=tenant.initial_admin_full_name,
            )
            self.repository.commit()
            self.registry_manager.add(created_tenant)
            logger.info(
                "Created tenant '%s' with id '%s'",
                created_tenant.slug,
                created_tenant.id,
            )
            return TenantCreateResponse(
                tenant=created_tenant,
                admin_setup_link=bootstrap_result.setup_link,
            )
        except Exception:
            self.repository.rollback()
            logger.exception("Failed to create tenant '%s'", tenant.slug)
            raise

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self.repository.get_by_slug(slug)

    def get_by_slug_or_raise(self, slug: str) -> Tenant:
        logger.info("Fetching tenant by slug '%s'", slug)
        tenant = self.repository.get_by_slug(slug)

        if tenant is None:
            raise TenantNotFoundError(f"Tenant '{slug}' was not found.")

        return tenant

    def list_active(self) -> list[Tenant]:
        logger.info("Listing active tenants")
        return self.repository.list_active()
