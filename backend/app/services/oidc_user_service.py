from datetime import UTC, datetime
from uuid import UUID

from app.models.tenant_user import TenantUser, TenantUserAuthSource
from app.repositories.tenant_user_repository import TenantUserRepository
from app.services.oidc_authentication_service import OIDCUserIdentity


class OIDCUserService:
    def __init__(self, repository: TenantUserRepository) -> None:
        self.repository = repository

    def provision(
        self,
        tenant_id: UUID,
        identity: OIDCUserIdentity,
    ) -> TenantUser:
        user = self.repository.get_by_tenant_and_email(
            tenant_id,
            identity.email,
        )

        try:
            if user is None:
                user = TenantUser(
                    tenant_id=tenant_id,
                    username=None,
                    email=identity.email,
                    full_name=identity.display_name or identity.email,
                    auth_source=TenantUserAuthSource.SSO,
                    password_hash=None,
                    external_subject=identity.subject,
                    is_active=True,
                    last_login_at=datetime.now(UTC),
                )
                user = self.repository.add(user)
            else:
                user.full_name = identity.display_name or user.full_name
                user.external_subject = identity.subject
                user.auth_source = TenantUserAuthSource.SSO
                user.last_login_at = datetime.now(UTC)

            self.repository.commit()
            self.repository.refresh(user)
            return user

        except Exception:
            self.repository.rollback()
            raise
