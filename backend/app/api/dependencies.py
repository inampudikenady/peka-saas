from fastapi import Depends
from sqlalchemy.orm import Session
from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.services.platform_admin_service import PlatformAdminService

from app.db.session import get_db
from app.repositories.tenant_repository import TenantRepository
from app.services.tenant_service import TenantService


def get_tenant_service(
    db: Session = Depends(get_db),
) -> TenantService:
    repository = TenantRepository(db)
    return TenantService(repository)

def get_platform_admin_service(
    db: Session = Depends(get_db),
) -> PlatformAdminService:
    repository = PlatformAdminRepository(db)
    return PlatformAdminService(repository)
