from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_admin_invite import PlatformAdminInvite, PlatformAdminInvitePurpose
from app.repositories.base import BaseRepository


class PlatformAdminInviteRepository(BaseRepository[PlatformAdminInvite]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, PlatformAdminInvite)

    def get_by_token_hash(self, token_hash: str) -> PlatformAdminInvite | None:
        return self.db.scalar(select(PlatformAdminInvite).where(PlatformAdminInvite.token_hash == token_hash))

    def get_unused(self, user_id: UUID, purpose: PlatformAdminInvitePurpose) -> list[PlatformAdminInvite]:
        stmt = select(PlatformAdminInvite).where(
            PlatformAdminInvite.user_id == user_id,
            PlatformAdminInvite.purpose == purpose,
            PlatformAdminInvite.used_at.is_(None),
        )
        return list(self.db.scalars(stmt).all())
