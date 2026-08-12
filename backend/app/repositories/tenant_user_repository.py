from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.tenant_user import TenantUser, TenantUserRole
from app.repositories.base import BaseRepository
from app.core.identity import normalize_email


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
            .where(func.lower(func.trim(TenantUser.email)) == normalize_email(email))
        )
        return self.db.scalars(stmt).one_or_none()

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
        return self.db.scalars(stmt).one_or_none()

    def update_external_subject_if_matches(
        self,
        tenant_id: UUID,
        user_id: UUID,
        expected_old_subject: str,
        new_subject: str,
    ) -> bool:
        stmt = (
            update(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .where(TenantUser.id == user_id)
            .where(TenantUser.external_subject == expected_old_subject)
            .values(external_subject=new_subject)
            .execution_options(synchronize_session="fetch")
        )
        result = self.db.execute(stmt)
        return result.rowcount == 1

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
        stmt = (
            select(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .order_by(TenantUser.full_name)
        )
        return list(self.db.scalars(stmt).all())

    def count_active_admins(self, tenant_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(TenantUser)
            .where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.is_active.is_(True),
                TenantUser.role == TenantUserRole.TENANT_ADMIN,
            )
        )
        return self.db.scalar(stmt) or 0
