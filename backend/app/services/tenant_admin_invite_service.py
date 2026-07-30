import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.models.tenant import Tenant
from app.models.tenant_admin_invite import TenantAdminInvite
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository
from app.core.url_builder import build_tenant_admin_setup_url
from app.schemas.tenant import TenantAdminInviteResponse
from app.models.tenant_audit_event import TenantAuditEvent
from app.core.logging import request_id_ctx


class TenantAdminInviteService:
    def __init__(self, repository: TenantAdminInviteRepository) -> None:
        self.repository = repository

    def create_invite(
        self,
        tenant: Tenant,
        email: str,
        full_name: str,
        created_by_platform_admin_id=None,
    ) -> tuple[TenantAdminInvite, str]:
        raw_token = secrets.token_urlsafe(48)
        token_hash = self.hash_token(raw_token)

        invite = TenantAdminInvite(
            tenant_id=tenant.id,
            email=email,
            full_name=full_name,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            created_by_platform_admin_id=created_by_platform_admin_id,
        )

        created_invite = self.repository.add(invite)
        return created_invite, raw_token

    def get_status(self, tenant: Tenant) -> TenantAdminInviteResponse | None:
        invite = self.repository.get_latest_for_tenant(tenant.id)
        if invite is None:
            return None
        return self._response(invite)

    def regenerate(
        self,
        tenant: Tenant,
        created_by_platform_admin_id,
    ) -> TenantAdminInviteResponse:
        previous = self.repository.get_latest_unused_for_tenant(tenant.id)
        if previous is None:
            latest = self.repository.get_latest_for_tenant(tenant.id)
            if latest is None:
                raise ValueError("No initial administrator invitation exists.")
            email, full_name = latest.email, latest.full_name
        else:
            previous.expires_at = datetime.now(UTC)
            email, full_name = previous.email, previous.full_name

        try:
            invite, raw_token = self.create_invite(
                tenant=tenant,
                email=email,
                full_name=full_name,
                created_by_platform_admin_id=created_by_platform_admin_id,
            )
            self.repository.commit()
            self.repository.refresh(invite)
        except Exception:
            self.repository.rollback()
            raise

        setup_link = build_tenant_admin_setup_url(
            slug=tenant.slug,
            token=raw_token,
            hostname=tenant.subdomain,
        )
        return self._response(invite, setup_link=setup_link)

    def update_recipient(
        self,
        tenant: Tenant,
        email: str,
        full_name: str,
        actor,
    ) -> TenantAdminInviteResponse:
        previous = self.repository.get_latest_for_tenant(tenant.id)
        if previous is None:
            raise ValueError("No initial administrator invitation exists.")
        if previous.used_at is not None:
            raise ValueError(
                "The initial invitation has already been used; manage administrators instead."
            )
        previous.expires_at = datetime.now(UTC)
        try:
            invite, raw_token = self.create_invite(
                tenant=tenant,
                email=email.strip().lower(),
                full_name=full_name.strip(),
                created_by_platform_admin_id=actor.id,
            )
            self.repository.db.add(TenantAuditEvent(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                tenant_display_name=tenant.display_name,
                actor_platform_admin_id=actor.id,
                actor_username=actor.username,
                action="INITIAL_ADMIN_RECIPIENT_UPDATED",
                changes={
                    "email": {"old": previous.email, "new": invite.email},
                    "full_name": {"old": previous.full_name, "new": invite.full_name},
                },
                request_id=request_id_ctx.get(),
            ))
            self.repository.commit()
            self.repository.refresh(invite)
        except Exception:
            self.repository.rollback()
            raise
        setup_link = build_tenant_admin_setup_url(
            slug=tenant.slug,
            token=raw_token,
            hostname=tenant.subdomain,
        )
        return self._response(invite, setup_link=setup_link)

    @staticmethod
    def _response(
        invite: TenantAdminInvite,
        setup_link: str | None = None,
    ) -> TenantAdminInviteResponse:
        if invite.used_at is not None:
            status = "used"
        elif invite.expires_at <= datetime.now(UTC):
            status = "expired"
        else:
            status = "pending"
        return TenantAdminInviteResponse(
            email=invite.email,
            full_name=invite.full_name,
            expires_at=invite.expires_at,
            used_at=invite.used_at,
            status=status,
            setup_link=setup_link,
        )

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
