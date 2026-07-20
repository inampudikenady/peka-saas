from app.models.tenant import Tenant
from app.repositories.tenant_sso_repository import TenantSSORepository
from app.repositories.tenant_user_repository import TenantUserRepository
from app.schemas.tenant import TenantPlatformSummary


class TenantPlatformSummaryService:
    def __init__(
        self,
        sso_repository: TenantSSORepository,
        user_repository: TenantUserRepository,
    ) -> None:
        self.sso_repository = sso_repository
        self.user_repository = user_repository

    def get(self, tenant: Tenant) -> TenantPlatformSummary:
        sso = self.sso_repository.get_by_tenant_id(tenant.id)
        local_admin = self.user_repository.get_by_tenant_and_username(
            tenant.id,
            f"admin_{tenant.slug}",
        )
        return TenantPlatformSummary(
            sso_enabled=bool(sso and sso.enabled),
            sso_redirect_uri=sso.redirect_uri if sso else None,
            local_admin_active=bool(local_admin and local_admin.is_active),
            active_user_count=self.user_repository.count_active_for_tenant(tenant.id),
        )
