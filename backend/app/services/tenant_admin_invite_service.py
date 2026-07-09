import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.models.tenant import Tenant
from app.models.tenant_admin_invite import TenantAdminInvite
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository


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

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
