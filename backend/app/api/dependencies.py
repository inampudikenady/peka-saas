from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.tenant_repository import TenantRepository
from app.services.tenant_service import TenantService


def get_tenant_service(
    db: Session = Depends(get_db),
) -> TenantService:
    repository = TenantRepository(db)
    return TenantService(repository)
