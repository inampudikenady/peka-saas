import logging
from app.models.tenant import Tenant
from app.models.tenant_sso_config import SSOProvider, TenantSSOConfig
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository
from app.repositories.tenant_sso_repository import TenantSSORepository
from app.services.tenant_admin_invite_service import TenantAdminInviteService
from app.core.url_builder import build_tenant_admin_setup_url


logger = logging.getLogger(__name__)


class TenantBootstrapResult:
    def __init__(self, setup_link: str) -> None:
        self.setup_link = setup_link


class TenantBootstrapService:
    def __init__(
        self,
        sso_repository: TenantSSORepository,
        invite_repository: TenantAdminInviteRepository,
    ) -> None:
        self.sso_repository = sso_repository
        self.invite_service = TenantAdminInviteService(invite_repository)

    def bootstrap(
        self,
        tenant: Tenant,
        admin_email: str,
        admin_full_name: str,
        created_by_platform_admin_id=None,
    ) -> TenantBootstrapResult:
        sso_config = TenantSSOConfig(
            tenant_id=tenant.id,
            provider=SSOProvider.GENERIC_OIDC,
            enabled=False,
        )
        self.sso_repository.add(sso_config)

        invite, raw_token = self.invite_service.create_invite(
            tenant=tenant,
            email=admin_email,
            full_name=admin_full_name,
            created_by_platform_admin_id=created_by_platform_admin_id,
        )

        setup_link = build_tenant_admin_setup_url(
            slug=tenant.slug,
            token=raw_token,
            hostname=tenant.subdomain,
        )
        logger.info("Generated tenant admin setup link for tenant '%s'", tenant.slug)

        return TenantBootstrapResult(setup_link=setup_link)
