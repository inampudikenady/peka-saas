from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tenant_user import TenantUser, TenantUserRole
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

    def get_by_tenant_and_external_subject(
        self,
        tenant_id: UUID,
        external_subject: str,
    ) -> TenantUser | None:
        stmt = (
            select(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .where(TenantUser.external_subject == external_subject)
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

    def count_active_for_tenant(self, tenant_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .where(TenantUser.is_active.is_(True))
        )
        return self.db.scalar(stmt) or 0

    def list_for_tenant(self, tenant_id: UUID) -> list[TenantUser]:
        stmt = select(TenantUser).where(TenantUser.tenant_id == tenant_id).order_by(TenantUser.full_name)
        return list(self.db.scalars(stmt).all())

    def count_active_admins(self, tenant_id: UUID) -> int:
        stmt = select(func.count()).select_from(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.is_active.is_(True),
            TenantUser.role == TenantUserRole.TENANT_ADMIN,
        )
        return self.db.scalar(stmt) or 0
