from typing import Optional

from app.core.exceptions import (
    TenantAlreadyExistsError,
    TenantDomainAlreadyExistsError,
    TenantNotFoundError,
)
from app.models.tenant import Tenant
from app.repositories.tenant_repository import TenantRepository
from app.schemas.tenant import TenantCreate


class TenantService:
    def __init__(self, repository: TenantRepository) -> None:
        self.repository = repository

    def create(self, tenant: TenantCreate) -> Tenant:
        if self.repository.exists_by_slug(tenant.slug):
            raise TenantAlreadyExistsError(f"Tenant '{tenant.slug}' already exists.")

        if tenant.primary_domain and self.repository.exists_by_domain(
            tenant.primary_domain
        ):
            raise TenantDomainAlreadyExistsError(
                f"Primary domain '{tenant.primary_domain}' is already in use."
            )

        entity = Tenant(
            slug=tenant.slug,
            name=tenant.name,
            display_name=tenant.display_name,
            primary_domain=tenant.primary_domain,
            subdomain=tenant.subdomain,
            timezone=tenant.timezone,
        )

        return self.repository.add(entity)

    def get_by_slug(self, slug: str) -> Optional[Tenant]:
        return self.repository.get_by_slug(slug)

    def get_by_slug_or_raise(self, slug: str) -> Tenant:
        tenant = self.repository.get_by_slug(slug)

        if tenant is None:
            raise TenantNotFoundError(f"Tenant '{slug}' was not found.")

        return tenant

    def list_active(self) -> list[Tenant]:
        return self.repository.list_active()
