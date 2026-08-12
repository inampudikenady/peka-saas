import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identity import normalize_email
from app.core.password_policy import PasswordPolicyError, validate_local_password
from app.core.security import hash_password
from app.core.url_builder import build_tenant_password_reset_url
from app.models.platform_admin import PlatformAdmin
from app.models.tenant import Tenant
from app.models.tenant_audit_event import TenantAuditEvent
from app.models.tenant_user import (
    DevelopmentEmail,
    TenantPasswordResetToken,
    TenantUser,
    TenantUserAuthSource,
    TenantUserRole,
)


class TenantPasswordResetError(ValueError):
    pass


class TenantPasswordResetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def request_for_email(self, tenant: Tenant, email: str) -> None:
        user = self.db.scalar(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant.id,
                func.lower(func.trim(TenantUser.email)) == normalize_email(email),
                TenantUser.auth_source == TenantUserAuthSource.LOCAL,
                TenantUser.is_active.is_(True),
            )
        )
        if user is None:
            return
        self._issue(tenant, user, actor=None)

    def request_by_platform_admin(
        self, tenant: Tenant, user_id: UUID, actor: PlatformAdmin
    ) -> None:
        user = self.db.get(TenantUser, user_id)
        if (
            user is None
            or user.tenant_id != tenant.id
            or user.role != TenantUserRole.TENANT_ADMIN
        ):
            raise TenantPasswordResetError("Tenant administrator was not found.")
        if user.auth_source != TenantUserAuthSource.LOCAL:
            raise TenantPasswordResetError(
                "Password is managed by the identity provider."
            )
        if not user.is_active:
            raise TenantPasswordResetError(
                "Password reset is unavailable for an inactive administrator."
            )
        self._issue(tenant, user, actor=actor)

    def _issue(
        self, tenant: Tenant, user: TenantUser, actor: PlatformAdmin | None
    ) -> None:
        if (
            settings.tenant_email_delivery_backend == "development_outbox"
            and settings.environment.lower()
            not in {"dev", "local", "development", "test"}
        ):
            raise TenantPasswordResetError(
                "The development email outbox is disabled in this environment."
            )
        now = datetime.now(UTC)
        for token in self.db.scalars(
            select(TenantPasswordResetToken).where(
                TenantPasswordResetToken.tenant_id == tenant.id,
                TenantPasswordResetToken.tenant_user_id == user.id,
                TenantPasswordResetToken.used_at.is_(None),
                TenantPasswordResetToken.expires_at > now,
            )
        ):
            token.expires_at = now

        raw_token = secrets.token_urlsafe(48)
        expires_at = now + timedelta(minutes=settings.tenant_password_reset_minutes)
        reset = TenantPasswordResetToken(
            tenant_id=tenant.id,
            tenant_user_id=user.id,
            requested_by_platform_admin_id=actor.id if actor else None,
            token_hash=self._hash_token(raw_token),
            expires_at=expires_at,
        )
        reset_url = build_tenant_password_reset_url(
            tenant.slug, raw_token, tenant.subdomain
        )
        body = (
            f"A password reset was requested for your PEKA account in "
            f"{tenant.display_name}.\n\nReset password: {reset_url}\n\n"
            f"This single-use link expires in {settings.tenant_password_reset_minutes} "
            "minutes. If you did not request this, ignore this message."
        )
        self.db.add(reset)
        self._deliver(
            DevelopmentEmail(
                tenant_id=tenant.id,
                recipient=user.email,
                subject=f"Reset your PEKA password for {tenant.display_name}",
                body_text=body,
                action_url=reset_url,
                delivery_state="captured",
            )
        )
        self.db.add(
            TenantAuditEvent(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                tenant_display_name=tenant.display_name,
                actor_platform_admin_id=actor.id if actor else None,
                actor_username=actor.username if actor else "tenant-self-service",
                action="tenant_password_reset_requested",
                changes={
                    "affected_user_id": str(user.id),
                    "affected_user_email": user.email,
                    "request_source": "platform_admin" if actor else "tenant_login",
                },
            )
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            # Do not propagate a database exception containing the development
            # email body or raw action URL into request logs.
            raise TenantPasswordResetError("Password reset delivery failed.") from None

    def _deliver(self, email: DevelopmentEmail) -> None:
        if settings.tenant_email_delivery_backend == "development_outbox":
            self.db.add(email)
            return
        raise TenantPasswordResetError("Tenant email delivery is not configured.")

    def reset(self, tenant: Tenant, raw_token: str, new_password: str) -> None:
        try:
            validate_local_password(new_password)
        except PasswordPolicyError as exc:
            raise TenantPasswordResetError(str(exc)) from exc
        now = datetime.now(UTC)
        reset = self.db.scalar(
            select(TenantPasswordResetToken)
            .where(
                TenantPasswordResetToken.tenant_id == tenant.id,
                TenantPasswordResetToken.token_hash == self._hash_token(raw_token),
                TenantPasswordResetToken.used_at.is_(None),
                TenantPasswordResetToken.expires_at > now,
            )
            .with_for_update()
        )
        if reset is None:
            raise TenantPasswordResetError(
                "This password reset link is invalid or has expired."
            )
        user = self.db.get(TenantUser, reset.tenant_user_id)
        if (
            user is None
            or user.tenant_id != tenant.id
            or user.auth_source != TenantUserAuthSource.LOCAL
            or not user.is_active
        ):
            raise TenantPasswordResetError(
                "This password reset link is invalid or has expired."
            )
        user.password_hash = hash_password(new_password)
        user.failed_login_attempts = 0
        user.locked = False
        reset.used_at = now
        self.db.add(
            TenantAuditEvent(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                tenant_display_name=tenant.display_name,
                actor_platform_admin_id=reset.requested_by_platform_admin_id,
                actor_username=(
                    "platform-admin-reset"
                    if reset.requested_by_platform_admin_id
                    else user.username or user.email
                ),
                action="tenant_password_reset_completed",
                changes={
                    "affected_user_id": str(user.id),
                    "affected_user_email": user.email,
                    "account_unlocked": True,
                    "failed_login_attempts_cleared": True,
                },
            )
        )
        self.db.commit()
