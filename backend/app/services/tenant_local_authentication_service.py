from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import TenantAuthenticationError
from app.core.security import verify_password
from app.models.tenant_user import TenantUser, TenantUserAuthSource
from app.repositories.tenant_user_repository import TenantUserRepository


class TenantLocalAuthenticationService:
    def __init__(self, repository: TenantUserRepository) -> None:
        self.repository = repository

    def authenticate(
        self,
        tenant_id: UUID,
        username: str,
        password: str,
    ) -> TenantUser:
        user = self.repository.get_by_tenant_and_username(tenant_id, username)

        password_valid = False
        if user is not None and user.password_hash:
            try:
                password_valid = verify_password(password, user.password_hash)
            except (TypeError, ValueError):
                password_valid = False

        if (
            user is None
            or user.auth_source != TenantUserAuthSource.LOCAL
            or not user.is_active
            or user.locked
            or not user.password_hash
            or not password_valid
        ):
            if (
                user is not None
                and user.auth_source == TenantUserAuthSource.LOCAL
                and user.is_active
                and not user.locked
            ):
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.locked = True
                self.repository.commit()
            raise TenantAuthenticationError("Invalid username or password.")

        try:
            user.last_login_at = datetime.now(UTC)
            user.failed_login_attempts = 0
            self.repository.commit()
            self.repository.refresh(user)
            return user
        except Exception:
            self.repository.rollback()
            raise
