import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.core.password_policy import PasswordPolicyError, validate_platform_password
from app.models.platform_admin import PlatformAdmin, PlatformAdminRole
from app.models.platform_admin_invite import PlatformAdminInvite, PlatformAdminInvitePurpose
from app.repositories.platform_admin_invite_repository import PlatformAdminInviteRepository
from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.schemas.platform_auth import PlatformInvitationResponse, PlatformUserCreate, PlatformUserUpdate

logger = logging.getLogger(__name__)


class PlatformUserError(Exception):
    pass


class PlatformUserService:
    def __init__(self, users: PlatformAdminRepository, invites: PlatformAdminInviteRepository) -> None:
        self.users = users
        self.invites = invites

    def list(self) -> list[PlatformAdmin]:
        return self.users.list_all()

    def get(self, user_id: UUID) -> PlatformAdmin:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise PlatformUserError("Platform user was not found.")
        return user

    def create(self, payload: PlatformUserCreate, actor: PlatformAdmin) -> PlatformInvitationResponse:
        if self.users.exists_by_username(payload.username) or self.users.exists_by_email(payload.email):
            raise PlatformUserError("Username or email is already in use.")
        user = PlatformAdmin(username=payload.username, email=payload.email, full_name=payload.full_name, role=payload.role, password_hash=None, is_active=False)
        try:
            user = self.users.add(user)
            invite, raw = self._new_invite(user.id, actor.id, PlatformAdminInvitePurpose.SETUP)
            self.users.commit()
            self.users.refresh(user)
        except Exception:
            self.users.rollback()
            raise
        return PlatformInvitationResponse(user=user, setup_link=self._reset_link(raw), expires_at=invite.expires_at)

    def update(self, user_id: UUID, payload: PlatformUserUpdate, actor: PlatformAdmin) -> PlatformAdmin:
        user = self.get(user_id)
        if user.id == actor.id and user.role == PlatformAdminRole.PLATFORM_ADMIN and payload.role != PlatformAdminRole.PLATFORM_ADMIN and self.users.count_active_admins() <= 1:
            raise PlatformUserError("The last active platform administrator cannot remove their own admin role.")
        existing = self.users.get_by_email(payload.email)
        if existing is not None and existing.id != user.id:
            raise PlatformUserError("Email is already in use.")
        user.email, user.full_name, user.role = payload.email, payload.full_name, payload.role
        self.users.commit(); self.users.refresh(user)
        return user

    def set_active(self, user_id: UUID, active: bool, actor: PlatformAdmin) -> PlatformAdmin:
        user = self.get(user_id)
        if not active and user.id == actor.id:
            raise PlatformUserError("You cannot deactivate your own account.")
        if not active and user.role == PlatformAdminRole.PLATFORM_ADMIN and user.is_active and self.users.count_active_admins() <= 1:
            raise PlatformUserError("The last active platform administrator cannot be deactivated.")
        user.is_active = active
        self.users.commit(); self.users.refresh(user)
        return user

    def password_reset(self, user_id: UUID, actor: PlatformAdmin) -> PlatformInvitationResponse:
        user = self.get(user_id)
        invite, raw = self._new_invite(user.id, actor.id, PlatformAdminInvitePurpose.PASSWORD_RESET)
        self.users.commit()
        return PlatformInvitationResponse(user=user, setup_link=self._reset_link(raw), expires_at=invite.expires_at)

    def consume_reset(self, raw_token: str, new_password: str) -> None:
        invite = self.invites.get_by_token_hash(self.hash_token(raw_token))
        if invite is None or invite.used_at is not None:
            raise PlatformUserError("Invalid or already used password setup token.")
        if invite.expires_at <= datetime.now(UTC):
            raise PlatformUserError("Password setup token has expired.")
        user = self.get(invite.user_id)
        try:
            validate_platform_password(new_password)
            user.password_hash = hash_password(new_password)
            user.is_active = True
            user.locked = False
            user.failed_login_attempts = 0
            invite.used_at = datetime.now(UTC)
            self.users.commit()
        except PasswordPolicyError as exc:
            self.users.rollback()
            raise PlatformUserError(str(exc)) from exc
        except Exception:
            self.users.rollback()
            raise
        logger.info("Platform user '%s' completed password setup", user.username)

    def change_password(self, user: PlatformAdmin, current_password: str, new_password: str) -> None:
        if not user.password_hash or not verify_password(current_password, user.password_hash):
            raise PlatformUserError("Current password is incorrect.")
        if verify_password(new_password, user.password_hash):
            raise PlatformUserError("New password must be different from the current password.")
        try:
            validate_platform_password(new_password)
            user.password_hash = hash_password(new_password)
            self.users.commit()
        except PasswordPolicyError as exc:
            self.users.rollback()
            raise PlatformUserError(str(exc)) from exc
        except Exception:
            self.users.rollback()
            raise
        logger.info("Platform user '%s' changed their password", user.username)

    def _new_invite(self, user_id: UUID, actor_id: UUID, purpose: PlatformAdminInvitePurpose):
        now = datetime.now(UTC)
        for old in self.invites.get_unused(user_id, purpose):
            old.expires_at = now
        raw = secrets.token_urlsafe(48)
        invite = PlatformAdminInvite(user_id=user_id, created_by_platform_admin_id=actor_id, purpose=purpose, token_hash=self.hash_token(raw), expires_at=now + timedelta(hours=24))
        return self.invites.add(invite), raw

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _reset_link(token: str) -> str:
        return f"{settings.platform_frontend_base_url.rstrip('/')}/platform/reset-password?token={token}"
