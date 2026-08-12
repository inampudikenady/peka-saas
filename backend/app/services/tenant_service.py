import logging

from sqlalchemy import select

from app.core.logging import request_id_ctx
from app.core.exceptions import (
    TenantAlreadyExistsError,
    TenantDomainAlreadyExistsError,
    TenantLifecycleError,
    TenantNotFoundError,
)
from app.core.url_builder import build_platform_hostname, build_tenant_url
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_audit_event import TenantAuditEvent
from app.models.platform_admin import PlatformAdmin
from app.repositories.tenant_repository import TenantRepository
from app.schemas.tenant import TenantCreate, TenantCreateResponse, TenantUpdate
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

    def _audit(
        self,
        tenant: Tenant,
        actor: PlatformAdmin | None,
        action: str,
        changes: dict,
    ) -> None:
        if not hasattr(self.repository, "db"):
            return
        self.repository.db.add(
            TenantAuditEvent(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                tenant_display_name=tenant.display_name,
                actor_platform_admin_id=actor.id if actor else None,
                actor_username=actor.username if actor else "system",
                action=action,
                changes=changes,
                request_id=request_id_ctx.get(),
            )
        )

    def create(
        self, tenant: TenantCreate, actor: PlatformAdmin | None = None
    ) -> TenantCreateResponse:
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
            name=tenant.display_name,
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
                created_by_platform_admin_id=actor.id if actor else None,
            )
            self._audit(
                created_tenant,
                actor,
                "TENANT_CREATED",
                {
                    "display_name": {"old": None, "new": tenant.display_name},
                    "timezone": {"old": None, "new": tenant.timezone},
                    "slug": {"old": None, "new": tenant.slug},
                },
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
        logger.info("Listing tenants")
        return self.repository.list_all()

    def update(
        self,
        slug: str,
        payload: TenantUpdate,
        actor: PlatformAdmin | None = None,
    ) -> Tenant:
        tenant = self.get_by_slug_or_raise(slug)
        changes: dict[str, dict[str, str]] = {}
        if (
            payload.display_name is not None
            and payload.display_name != tenant.display_name
        ):
            changes["display_name"] = {
                "old": tenant.display_name,
                "new": payload.display_name,
            }
            tenant.display_name = payload.display_name
            tenant.name = payload.display_name
        if payload.timezone is not None and payload.timezone != tenant.timezone:
            changes["timezone"] = {"old": tenant.timezone, "new": payload.timezone}
            tenant.timezone = payload.timezone
        if not changes:
            return tenant
        try:
            self._audit(tenant, actor, "TENANT_UPDATED", changes)
            self.repository.commit()
            self.repository.refresh(tenant)
            self.registry_manager.add(tenant)
            return tenant
        except Exception:
            self.repository.rollback()
            raise

    def set_active(
        self,
        slug: str,
        active: bool,
        actor: PlatformAdmin | None = None,
    ) -> Tenant:
        tenant = self.get_by_slug_or_raise(slug)
        old_status = tenant.status
        tenant.status = TenantStatus.ACTIVE if active else TenantStatus.SUSPENDED
        try:
            self._audit(
                tenant,
                actor,
                "TENANT_ACTIVATED" if active else "TENANT_DEACTIVATED",
                {"status": {"old": old_status.value, "new": tenant.status.value}},
            )
            self.repository.commit()
            self.repository.refresh(tenant)
            self.registry_manager.add(tenant)
            return tenant
        except Exception:
            self.repository.rollback()
            raise

    def delete(
        self,
        slug: str,
        confirmation: str,
        actor: PlatformAdmin | None = None,
    ) -> None:
        tenant = self.get_by_slug_or_raise(slug)
        if confirmation != slug:
            raise TenantLifecycleError("Tenant deletion confirmation does not match.")
        if tenant.status == TenantStatus.ACTIVE:
            raise TenantLifecycleError("Deactivate the tenant before deleting it.")
        try:
            self._audit(
                tenant,
                actor,
                "TENANT_DELETED",
                {"status": {"old": tenant.status.value, "new": "deleted"}},
            )
            self.repository.delete(tenant)
            self.repository.commit()
            self.registry_manager.registry.remove_by_slug(slug)
        except Exception:
            self.repository.rollback()
            raise

    def list_audit_events(self, slug: str) -> list[TenantAuditEvent]:
        return list(
            self.repository.db.scalars(
                select(TenantAuditEvent)
                .where(TenantAuditEvent.tenant_slug == slug)
                .order_by(TenantAuditEvent.created_at.desc())
                .limit(200)
            ).all()
        )
