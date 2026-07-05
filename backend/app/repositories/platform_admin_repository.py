from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_admin import PlatformAdmin
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
