import logging
from datetime import datetime, UTC

from app.core.security import hash_password, verify_password
from app.models.platform_admin import PlatformAdmin
from app.repositories.platform_admin_repository import PlatformAdminRepository

logger = logging.getLogger(__name__)


class PlatformAdminService:
    def __init__(self, repository: PlatformAdminRepository) -> None:
        self.repository = repository

    def create_admin(
        self,
        username: str,
        email: str,
        password: str,
        full_name: str,
        is_super_admin: bool = False,
    ) -> PlatformAdmin:
        admin = PlatformAdmin(
            username=username,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            is_super_admin=is_super_admin,
        )

        try:
            created_admin = self.repository.add(admin)
            self.repository.commit()
            logger.info("Created platform admin '%s'", username)
            return created_admin
        except Exception:
            self.repository.rollback()
            logger.exception("Failed to create platform admin '%s'", username)
            raise

    def authenticate(self, username: str, password: str) -> PlatformAdmin | None:
        admin = self.repository.get_by_username(username)

        if admin is None:
            return None

        if not admin.is_active or admin.locked:
            return None

        if not verify_password(password, admin.password_hash):
            self.record_failed_login(admin)
            return None

        self.record_successful_login(admin)
        return admin

    def get_by_id(self, admin_id) -> PlatformAdmin | None:
        return self.repository.get_by_id(admin_id)

    def record_successful_login(self, admin: PlatformAdmin) -> None:
        admin.failed_login_attempts = 0
        admin.last_login_at = datetime.now(UTC)

        self.repository.commit()
        self.repository.refresh(admin)

    def record_failed_login(self, admin: PlatformAdmin) -> None:
        admin.failed_login_attempts += 1

        if admin.failed_login_attempts >= 5:
            admin.locked = True

        self.repository.commit()
        self.repository.refresh(admin)
