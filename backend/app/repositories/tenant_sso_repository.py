from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_sso_config import TenantSSOConfig
from app.repositories.base import BaseRepository


class TenantSSORepository(BaseRepository[TenantSSOConfig]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TenantSSOConfig)

    def get_by_tenant_id(self, tenant_id: UUID) -> Optional[TenantSSOConfig]:
        stmt = select(TenantSSOConfig).where(TenantSSOConfig.tenant_id == tenant_id)
        return self.db.scalar(stmt)

    def exists_for_tenant(self, tenant_id: UUID) -> bool:
        return self.get_by_tenant_id(tenant_id) is not None
