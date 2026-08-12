import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.identity import normalize_email
from app.core.security import hash_password, verify_password
from app.core.url_builder import build_tenant_admin_setup_url
from app.models.tenant_admin_invite import TenantAdminInvite, TenantInvitePurpose
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.tenant_user_repository import TenantUserRepository
from app.schemas.tenant_user import TenantUserCreate, TenantUserInvitationResponse
from app.services.tenant_admin_invite_service import TenantAdminInviteService


class TenantUserManagementError(Exception):
    pass


class TenantUserManagementService:
    def __init__(
        self,
        repository: TenantUserRepository,
        invites: TenantAdminInviteRepository | None = None,
        tenants: TenantRepository | None = None,
    ) -> None:
        self.repository, self.invites, self.tenants = repository, invites, tenants

    def list(self, tenant_id: UUID):
        return self.repository.list_for_tenant(tenant_id)

    def get(self, tenant_id: UUID, user_id: UUID):
        user = self.repository.get_by_id(user_id)
        if user is None or user.tenant_id != tenant_id:
            raise TenantUserManagementError("Tenant user was not found.")
        return user

    def create(
        self, tenant_id: UUID, payload: TenantUserCreate, actor: TenantUser
    ) -> TenantUserInvitationResponse:
        email = normalize_email(payload.email)
        if self.repository.get_by_tenant_and_email(
            tenant_id, email
        ) or self.repository.get_by_tenant_and_username(tenant_id, payload.username):
            raise TenantUserManagementError("Username or email is already in use.")
        user = TenantUser(
            tenant_id=tenant_id,
            username=payload.username,
            email=email,
            full_name=payload.full_name,
            auth_source=TenantUserAuthSource.LOCAL,
            role=payload.role,
            password_hash=None,
            is_active=False,
        )
        try:
            user = self.repository.add(user)
            invite, raw = self._invite(user, actor, TenantInvitePurpose.USER_SETUP)
            self.repository.commit()
            self.repository.refresh(user)
        except Exception:
            self.repository.rollback()
            raise
        return TenantUserInvitationResponse(
            user=user,
            setup_link=self._link(tenant_id, raw),
            expires_at=invite.expires_at,
        )

    def reset(
        self, tenant_id: UUID, user_id: UUID, actor: TenantUser
    ) -> TenantUserInvitationResponse:
        user = self.get(tenant_id, user_id)
        if user.auth_source != TenantUserAuthSource.LOCAL:
            raise TenantUserManagementError(
                "Password is managed by the identity provider."
            )
        invite, raw = self._invite(user, actor, TenantInvitePurpose.PASSWORD_RESET)
        self.repository.commit()
        return TenantUserInvitationResponse(
            user=user,
            setup_link=self._link(tenant_id, raw),
            expires_at=invite.expires_at,
        )

    def change_password(self, user: TenantUser, current: str, new: str) -> None:
        if user.auth_source != TenantUserAuthSource.LOCAL:
            raise TenantUserManagementError(
                "Password is managed by the identity provider."
            )
        if not user.password_hash or not verify_password(current, user.password_hash):
            raise TenantUserManagementError("Current password is incorrect.")
        if verify_password(new, user.password_hash):
            raise TenantUserManagementError("New password must be different.")
        user.password_hash = hash_password(new)
        self.repository.commit()

    def set_role(self, tenant_id, user_id, role, actor):
        user = self.get(tenant_id, user_id)
        if (
            user.role == TenantUserRole.TENANT_ADMIN
            and role != TenantUserRole.TENANT_ADMIN
            and user.is_active
            and self.repository.count_active_admins(tenant_id) <= 1
        ):
            raise TenantUserManagementError(
                "The last active tenant administrator cannot be demoted."
            )
        user.role = role
        self.repository.commit()
        self.repository.refresh(user)
        return user

    def set_active(self, tenant_id, user_id, active, actor):
        user = self.get(tenant_id, user_id)
        if not active and user.id == actor.id:
            raise TenantUserManagementError("You cannot deactivate your own account.")
        if (
            not active
            and user.role == TenantUserRole.TENANT_ADMIN
            and user.is_active
            and self.repository.count_active_admins(tenant_id) <= 1
        ):
            raise TenantUserManagementError(
                "The last active tenant administrator cannot be deactivated."
            )
        user.is_active = active
        self.repository.commit()
        self.repository.refresh(user)
        return user

    def _invite(self, user, actor, purpose):
        assert self.invites is not None
        now = datetime.now(UTC)
        for old in self.invites.get_unused_for_user(user.id, purpose):
            old.expires_at = now
        raw = secrets.token_urlsafe(48)
        invite = TenantAdminInvite(
            tenant_id=user.tenant_id,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            purpose=purpose,
            token_hash=TenantAdminInviteService.hash_token(raw),
            expires_at=now + timedelta(hours=24),
        )
        return self.invites.add(invite), raw

    def _link(self, tenant_id, raw):
        assert self.tenants is not None
        tenant = self.tenants.get_by_id(tenant_id)
        return build_tenant_admin_setup_url(tenant.slug, raw, tenant.subdomain)
