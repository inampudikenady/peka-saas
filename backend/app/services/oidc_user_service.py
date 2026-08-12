from datetime import UTC, datetime
import logging
from typing import NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.identity import normalize_email
from app.core.logging import request_id_ctx
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.repositories.tenant_user_repository import TenantUserRepository
from app.services.oidc_authentication_service import OIDCUserIdentity
from app.core.exceptions import OIDCUserAuthorizationError


logger = logging.getLogger(__name__)


class OIDCUserService:
    def __init__(self, repository: TenantUserRepository) -> None:
        self.repository = repository

    def provision(
        self,
        tenant_id: UUID,
        identity: OIDCUserIdentity,
        tenant_slug: str | None = None,
    ) -> TenantUser:
        user = None
        lookup_source = "none"
        migration_result = "not_applicable"

        if identity.oid:
            user = self.repository.get_by_tenant_and_external_subject(
                tenant_id, identity.oid
            )
            if user is not None:
                lookup_source = "oid"
        elif identity.sub:
            user = self.repository.get_by_tenant_and_external_subject(
                tenant_id, identity.sub
            )
            if user is not None:
                lookup_source = "sub"

        if user is None and identity.oid and identity.sub:
            legacy_user = self.repository.get_by_tenant_and_external_subject(
                tenant_id, identity.sub
            )
            if legacy_user is not None:
                self._authorize_user(
                    legacy_user,
                    tenant_id,
                    tenant_slug,
                    lookup_source="legacy_sub",
                    require_sso=True,
                )
                migration_transaction_reset = False
                try:
                    migrated = self.repository.update_external_subject_if_matches(
                        tenant_id=tenant_id,
                        user_id=legacy_user.id,
                        expected_old_subject=identity.sub,
                        new_subject=identity.oid,
                    )
                except IntegrityError:
                    # A unique subject collision is an authorization conflict,
                    # never permission to rebind either identity.
                    self.repository.rollback()
                    migration_transaction_reset = True
                    migrated = False
                if not migrated:
                    # A concurrent callback may have completed the same migration.
                    if not migration_transaction_reset:
                        self.repository.rollback()
                    migrated_user = self.repository.get_by_tenant_and_external_subject(
                        tenant_id, identity.oid
                    )
                    if migrated_user is None or migrated_user.id != legacy_user.id:
                        self._reject(
                            tenant_id,
                            tenant_slug,
                            legacy_user,
                            "legacy_subject_migration_conflict",
                            "legacy_sub",
                        )
                    user = migrated_user
                    migration_result = "already_migrated"
                else:
                    user = legacy_user
                    migration_result = "migrated"
                lookup_source = "legacy_sub"

        if user is None:
            user = self.repository.get_by_tenant_and_email(
                tenant_id,
                normalize_email(identity.email),
            )
            if user is not None:
                lookup_source = "email"
                allowed_subjects = {
                    value for value in (identity.oid, identity.sub) if value
                }
                if (
                    user.external_subject
                    and user.external_subject not in allowed_subjects
                ):
                    self._reject(
                        tenant_id,
                        tenant_slug,
                        user,
                        "external_subject_mismatch",
                        lookup_source,
                    )

        if user is not None:
            self._authorize_user(user, tenant_id, tenant_slug, lookup_source)

        try:
            if user is None:
                user = TenantUser(
                    tenant_id=tenant_id,
                    username=None,
                    email=normalize_email(identity.email),
                    full_name=identity.display_name or identity.email,
                    auth_source=TenantUserAuthSource.SSO,
                    password_hash=None,
                    external_subject=identity.subject,
                    is_active=True,
                    last_login_at=datetime.now(UTC),
                    role=TenantUserRole.TENANT_USER,
                )
                user = self.repository.add(user)
                lookup_source = "new_user"
            else:
                user.full_name = identity.display_name or user.full_name
                if not user.external_subject:
                    user.external_subject = identity.subject
                user.auth_source = TenantUserAuthSource.SSO
                user.last_login_at = datetime.now(UTC)

            self.repository.commit()
            self.repository.refresh(user)
            if lookup_source == "legacy_sub":
                logger.info(
                    "oidc_legacy_subject_migrated",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_slug": tenant_slug,
                        "matched_user_id": str(user.id),
                        "lookup_source": lookup_source,
                        "authorization_result": "allowed",
                        "migration_result": migration_result,
                        "request_id": request_id_ctx.get(),
                    },
                )
            logger.info(
                "OIDC tenant user authorized",
                extra={
                    "tenant_id": str(tenant_id),
                    "tenant_slug": tenant_slug,
                    "matched_user_id": str(user.id),
                    "lookup_source": lookup_source,
                    "authorization_result": "allowed",
                    "migration_result": migration_result,
                    "request_id": request_id_ctx.get(),
                },
            )
            return user

        except Exception:
            self.repository.rollback()
            raise

    def _authorize_user(
        self,
        user: TenantUser,
        tenant_id: UUID,
        tenant_slug: str | None,
        lookup_source: str,
        require_sso: bool = False,
    ) -> None:
        if user.tenant_id != tenant_id:
            self._reject(tenant_id, tenant_slug, user, "tenant_mismatch", lookup_source)
        if require_sso and user.auth_source != TenantUserAuthSource.SSO:
            self._reject(
                tenant_id, tenant_slug, user, "legacy_subject_not_sso", lookup_source
            )
        if not user.is_active:
            self._reject(tenant_id, tenant_slug, user, "inactive_user", lookup_source)
        if user.locked:
            self._reject(tenant_id, tenant_slug, user, "locked_user", lookup_source)

    @staticmethod
    def _reject(
        tenant_id: UUID,
        tenant_slug: str | None,
        user: TenantUser | None,
        reason: str,
        lookup_source: str,
    ) -> NoReturn:
        logger.warning(
            "OIDC tenant user authorization rejected",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_slug": tenant_slug,
                "matched_user_id": str(user.id) if user is not None else None,
                "lookup_source": lookup_source,
                "authorization_result": "rejected",
                "migration_result": "not_applied",
                "rejection_reason": reason,
                "request_id": request_id_ctx.get(),
            },
        )
        raise OIDCUserAuthorizationError("User is not authorized for this tenant.")
