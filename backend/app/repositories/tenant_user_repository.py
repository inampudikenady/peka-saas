from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_user import TenantUser
from app.repositories.base import BaseRepository


class TenantUserRepository(BaseRepository[TenantUser]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TenantUser)

    def get_by_tenant_and_email(
        self,
        tenant_id: UUID,
        email: str,
    ) -> TenantUser | None:
        stmt = (
            select(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .where(TenantUser.email == email)
        )
        return self.db.scalar(stmt)

    def get_by_tenant_and_username(
        self,
        tenant_id: UUID,
        username: str,
    ) -> TenantUser | None:
        stmt = (
            select(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .where(TenantUser.username == username)
        )
        return self.db.scalar(stmt)
