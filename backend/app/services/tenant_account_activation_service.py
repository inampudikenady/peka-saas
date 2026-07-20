from datetime import UTC, datetime
from uuid import UUID
from app.core.exceptions import (
    InvalidTenantInviteTokenError,
    TenantInviteAlreadyUsedError,
    TenantInviteExpiredError,
    TenantUserAlreadyExistsError,
    TenantUsernameAlreadyExistsError,
)

from app.core.security import hash_password
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.repositories.tenant_repository import TenantRepository
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository
from app.repositories.tenant_user_repository import TenantUserRepository
from app.services.tenant_admin_invite_service import TenantAdminInviteService


class TenantAccountActivationService:
    def __init__(
        self,
        invite_repository: TenantAdminInviteRepository,
        user_repository: TenantUserRepository,
        tenant_repository: TenantRepository,
    ) -> None:
        self.invite_repository = invite_repository
        self.user_repository = user_repository
        self.tenant_repository = tenant_repository

    def activate(
        self,
        token: str,
        password: str,
        expected_tenant_id: UUID,
    ) -> TenantUser:
        token_hash = TenantAdminInviteService.hash_token(token)
        invite = self.invite_repository.get_by_token_hash(token_hash)

        if invite is None:
            raise InvalidTenantInviteTokenError("Invalid setup token.")

        if invite.used_at is not None:
            raise TenantInviteAlreadyUsedError("Setup token has already been used.")

        if invite.expires_at < datetime.now(UTC):
            raise TenantInviteExpiredError("Setup token has expired.")

        tenant = self.tenant_repository.get_by_id(invite.tenant_id)
        if tenant is None:
            raise InvalidTenantInviteTokenError("Invalid setup token.")

        if tenant.id != expected_tenant_id:
            raise InvalidTenantInviteTokenError("Invalid setup token.")

        if invite.user_id is not None:
            user = self.user_repository.get_by_id(invite.user_id)
            if user is None or user.tenant_id != expected_tenant_id:
                raise InvalidTenantInviteTokenError("Invalid setup token.")
            try:
                user.password_hash = hash_password(password)
                user.is_active = True
                invite.used_at = datetime.now(UTC)
                self.user_repository.commit()
                self.user_repository.refresh(user)
                return user
            except Exception:
                self.user_repository.rollback()
                raise

        username = f"admin_{tenant.slug}"

        existing_user = self.user_repository.get_by_tenant_and_email(
            invite.tenant_id,
            invite.email,
        )

        if existing_user is not None:
            raise TenantUserAlreadyExistsError("Tenant admin user already exists.")

        existing_username = self.user_repository.get_by_tenant_and_username(
            invite.tenant_id,
            username,
        )
        if existing_username is not None:
            raise TenantUsernameAlreadyExistsError(
                f"Tenant username '{username}' already exists."
            )

        user = TenantUser(
            tenant_id=invite.tenant_id,
            username=username,
            email=invite.email,
            full_name=invite.full_name,
            auth_source=TenantUserAuthSource.LOCAL,
            password_hash=hash_password(password),
            is_active=True,
            role=TenantUserRole.TENANT_ADMIN,
        )

        try:
            created_user = self.user_repository.add(user)
            invite.used_at = datetime.now(UTC)
            self.user_repository.commit()
            self.user_repository.refresh(created_user)

            return created_user
        except Exception:
            self.user_repository.rollback()
            raise
