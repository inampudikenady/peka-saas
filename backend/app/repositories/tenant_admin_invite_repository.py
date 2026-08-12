from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_admin_invite import TenantAdminInvite
from app.models.tenant_admin_invite import TenantInvitePurpose
from app.repositories.base import BaseRepository


class TenantAdminInviteRepository(BaseRepository[TenantAdminInvite]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TenantAdminInvite)

    def get_by_token_hash(self, token_hash: str) -> TenantAdminInvite | None:
        stmt = select(TenantAdminInvite).where(
            TenantAdminInvite.token_hash == token_hash
        )
        return self.db.scalar(stmt)

    def get_latest_unused_for_tenant(
        self,
        tenant_id: UUID,
    ) -> TenantAdminInvite | None:
        stmt = (
            select(TenantAdminInvite)
            .where(TenantAdminInvite.tenant_id == tenant_id)
            .where(TenantAdminInvite.used_at.is_(None))
            .where(TenantAdminInvite.purpose == TenantInvitePurpose.BOOTSTRAP)
            .order_by(TenantAdminInvite.created_at.desc())
        )
        return self.db.scalar(stmt)

    def get_latest_for_tenant(self, tenant_id: UUID) -> TenantAdminInvite | None:
        stmt = (
            select(TenantAdminInvite)
            .where(TenantAdminInvite.tenant_id == tenant_id)
            .where(TenantAdminInvite.purpose == TenantInvitePurpose.BOOTSTRAP)
            .order_by(TenantAdminInvite.created_at.desc())
        )
        return self.db.scalar(stmt)

    def get_unused_for_user(
        self, user_id: UUID, purpose: TenantInvitePurpose
    ) -> list[TenantAdminInvite]:
        stmt = select(TenantAdminInvite).where(
            TenantAdminInvite.user_id == user_id,
            TenantAdminInvite.purpose == purpose,
            TenantAdminInvite.used_at.is_(None),
        )
        return list(self.db.scalars(stmt).all())
