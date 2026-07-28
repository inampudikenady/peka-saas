from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.core.tenant_registry import tenant_registry

from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.repositories.platform_admin_invite_repository import PlatformAdminInviteRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.tenant_admin_invite_repository import TenantAdminInviteRepository
from app.repositories.tenant_user_repository import TenantUserRepository
from app.repositories.tenant_sso_repository import TenantSSORepository

from app.services.platform_admin_service import PlatformAdminService
from app.services.platform_user_service import PlatformUserService
from app.services.tenant_registry_manager import TenantRegistryManager
from app.services.tenant_bootstrap_service import TenantBootstrapService
from app.services.tenant_account_activation_service import TenantAccountActivationService
from app.services.tenant_service import TenantService
from app.services.tenant_sso_service import TenantSSOService
from app.repositories.tenant_oidc_auth_session_repository import (
    TenantOIDCAuthSessionRepository,
)
from app.services.oidc_discovery_service import OIDCDiscoveryService
from app.services.oidc_authentication_service import OIDCAuthenticationService
from app.services.oidc_user_service import OIDCUserService
from app.services.tenant_oidc_auth_session_service import (
    TenantOIDCAuthSessionService,
)
from app.services.tenant_local_authentication_service import (
    TenantLocalAuthenticationService,
)
from app.services.tenant_admin_invite_service import TenantAdminInviteService
from app.services.tenant_platform_summary_service import TenantPlatformSummaryService
from app.services.tenant_user_management_service import TenantUserManagementService
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.ai_conversation_repository import AIConversationRepository
from app.services.connector_service import ConnectorService
from app.services.knowledge_service import KnowledgeService
from app.services.ai_conversation_service import AIConversationService
from app.services.provider_factory import embedding_provider, vector_store


def get_tenant_service(
    db: Session = Depends(get_db),
) -> TenantService:
    repository = TenantRepository(db)
    registry_manager = TenantRegistryManager(tenant_registry)
    bootstrap_service = TenantBootstrapService(
        sso_repository=TenantSSORepository(db),
        invite_repository=TenantAdminInviteRepository(db),
    )
    return TenantService(repository, registry_manager, bootstrap_service)


def get_platform_admin_service(
    db: Session = Depends(get_db),
) -> PlatformAdminService:
    repository = PlatformAdminRepository(db)
    return PlatformAdminService(repository)


def get_platform_user_service(
    db: Session = Depends(get_db),
) -> PlatformUserService:
    return PlatformUserService(
        PlatformAdminRepository(db),
        PlatformAdminInviteRepository(db),
    )


def get_tenant_account_activation_service(
    db: Session = Depends(get_db),
) -> TenantAccountActivationService:
    return TenantAccountActivationService(
        invite_repository=TenantAdminInviteRepository(db),
        user_repository=TenantUserRepository(db),
        tenant_repository=TenantRepository(db),
    )


def get_tenant_sso_service(
    db: Session = Depends(get_db),
) -> TenantSSOService:
    return TenantSSOService(
        repository=TenantSSORepository(db),
        tenant_repository=TenantRepository(db),
        discovery_service=OIDCDiscoveryService(),
    )


def get_tenant_oidc_auth_session_service(
    db: Session = Depends(get_db),
) -> TenantOIDCAuthSessionService:
    return TenantOIDCAuthSessionService(
        repository=TenantOIDCAuthSessionRepository(db),
    )


def get_oidc_authentication_service() -> OIDCAuthenticationService:
    return OIDCAuthenticationService()


def get_oidc_user_service(
    db: Session = Depends(get_db),
) -> OIDCUserService:
    return OIDCUserService(
        repository=TenantUserRepository(db),
    )


def get_tenant_local_authentication_service(
    db: Session = Depends(get_db),
) -> TenantLocalAuthenticationService:
    return TenantLocalAuthenticationService(TenantUserRepository(db))


def get_tenant_admin_invite_service(
    db: Session = Depends(get_db),
) -> TenantAdminInviteService:
    return TenantAdminInviteService(TenantAdminInviteRepository(db))


def get_tenant_platform_summary_service(
    db: Session = Depends(get_db),
) -> TenantPlatformSummaryService:
    return TenantPlatformSummaryService(
        sso_repository=TenantSSORepository(db),
        user_repository=TenantUserRepository(db),
    )


def get_tenant_user_management_service(
    db: Session = Depends(get_db),
) -> TenantUserManagementService:
    return TenantUserManagementService(TenantUserRepository(db), TenantAdminInviteRepository(db), TenantRepository(db))


def get_connector_service(db: Session = Depends(get_db)) -> ConnectorService:
    return ConnectorService(
        ConnectorRepository(db),
        TenantRepository(db),
        connector_limit=settings.connector_max_active_per_tenant,
    )


def get_knowledge_service(
    db: Session = Depends(get_db),
) -> KnowledgeService:
    """Compose the sole tenant retrieval boundary outside its consumers."""
    return KnowledgeService(
        DocumentRepository(db),
        embedding_provider(),
        vector_store(),
    )


def get_ai_conversation_service(
    db: Session = Depends(get_db),
) -> AIConversationService:
    return AIConversationService(AIConversationRepository(db))
