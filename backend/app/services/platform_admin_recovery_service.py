"""Local-only emergency recovery for an existing Platform Administrator."""

import logging
from datetime import UTC, datetime

from app.core.password_policy import PasswordPolicyError, validate_platform_password
from app.core.security import hash_password
from app.models.platform_admin import PlatformAdmin, PlatformAdminRole
from app.repositories.platform_admin_repository import PlatformAdminRepository

logger = logging.getLogger(__name__)


class PlatformAdminRecoveryError(Exception):
    pass


class PlatformAdminRecoveryService:
    def __init__(self, repository: PlatformAdminRepository) -> None:
        self.repository = repository

    def resolve(
        self,
        *,
        email: str | None = None,
        username: str | None = None,
    ) -> PlatformAdmin:
        if (email is None) == (username is None):
            raise PlatformAdminRecoveryError(
                "Select exactly one account by email or username."
            )
        account = (
            self.repository.get_by_email(email)
            if email is not None
            else self.repository.get_by_username(username)
        )
        if account is None:
            raise PlatformAdminRecoveryError("Platform administrator was not found.")
        if account.role != PlatformAdminRole.PLATFORM_ADMIN:
            raise PlatformAdminRecoveryError(
                "The selected account is not a Platform Admin."
            )
        return account

    def reset_password(
        self,
        account: PlatformAdmin,
        new_password: str,
    ) -> PlatformAdmin:
        if account.role != PlatformAdminRole.PLATFORM_ADMIN:
            raise PlatformAdminRecoveryError(
                "The selected account is not a Platform Admin."
            )
        try:
            validate_platform_password(new_password)
            account.password_hash = hash_password(new_password)
            account.is_active = True
            account.locked = False
            account.failed_login_attempts = 0
            self.repository.commit()
            self.repository.refresh(account)
        except PasswordPolicyError as exc:
            self.repository.rollback()
            raise PlatformAdminRecoveryError(
                f"Password does not meet policy requirements. {exc}"
            ) from exc
        except Exception as exc:
            self.repository.rollback()
            raise PlatformAdminRecoveryError("Password recovery failed.") from exc

        execution_timestamp = datetime.now(UTC).isoformat()
        logger.info(
            "platform_admin_password_recovered "
            "user_id=%s username=%s email=%s execution_timestamp=%s "
            "command_source=local_cli",
            account.id,
            account.username,
            account.email,
            execution_timestamp,
        )
        return account
