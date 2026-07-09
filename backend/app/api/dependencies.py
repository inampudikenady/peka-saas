from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.tenant_registry import tenant_registry

from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository
from app.repositories.tenant_user_repository import TenantUserRepository
from app.repositories.tenant_sso_repository import TenantSSORepository

from app.services.platform_admin_service import PlatformAdminService
from app.services.tenant_registry_manager import TenantRegistryManager
from app.services.tenant_bootstrap_service import TenantBootstrapService
from app.services.tenant_account_activation_service import TenantAccountActivationService
from app.services.tenant_service import TenantService


def get_tenant_service(
    db: Session = Depends(get_db),
) -> TenantService:
    repository = TenantRepository(db)
    registry_manager = TenantRegistryManager(tenant_registry)
    bootstrap_service = TenantBootstrapService(
        sso_repository=TenantSSORepository(db),
        invite_repository=TenantAdminInviteRepository(db),
    )
    return TenantService(repository, registry_manager, bootstrap_service)


def get_platform_admin_service(
    db: Session = Depends(get_db),
) -> PlatformAdminService:
    repository = PlatformAdminRepository(db)
    return PlatformAdminService(repository)


def get_tenant_account_activation_service(
    db: Session = Depends(get_db),
) -> TenantAccountActivationService:
    return TenantAccountActivationService(
        invite_repository=TenantAdminInviteRepository(db),
        user_repository=TenantUserRepository(db),
        tenant_repository=TenantRepository(db),
    )
