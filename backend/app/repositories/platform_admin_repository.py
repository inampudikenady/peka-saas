from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.platform_admin import PlatformAdmin
from app.models.platform_admin import PlatformAdminRole
from app.repositories.base import BaseRepository


class PlatformAdminRepository(BaseRepository[PlatformAdmin]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, PlatformAdmin)

    def get_by_id(self, admin_id: UUID) -> Optional[PlatformAdmin]:
        return self.db.get(PlatformAdmin, admin_id)

    def get_by_username(self, username: str) -> Optional[PlatformAdmin]:
        stmt = select(PlatformAdmin).where(PlatformAdmin.username == username)
        return self.db.scalar(stmt)

    def get_by_email(self, email: str) -> Optional[PlatformAdmin]:
        stmt = select(PlatformAdmin).where(PlatformAdmin.email == email)
        return self.db.scalar(stmt)

    def exists_by_username(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def exists_by_email(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def list_all(self) -> list[PlatformAdmin]:
        return list(
            self.db.scalars(
                select(PlatformAdmin).order_by(PlatformAdmin.username)
            ).all()
        )

    def count_active_admins(self) -> int:
        stmt = (
            select(func.count())
            .select_from(PlatformAdmin)
            .where(
                PlatformAdmin.is_active.is_(True),
                PlatformAdmin.role == PlatformAdminRole.PLATFORM_ADMIN,
            )
        )
        return self.db.scalar(stmt) or 0
