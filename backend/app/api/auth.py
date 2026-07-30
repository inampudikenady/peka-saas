from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.api.tenant_context import get_current_tenant_context
from app.core.config import settings
from app.core.security import decode_access_token, decode_tenant_access_token
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.platform_admin import PlatformAdmin, PlatformAdminRole
from app.models.tenant_user import TenantUser, TenantUserRole
from app.repositories.platform_admin_repository import PlatformAdminRepository
from app.repositories.tenant_user_repository import TenantUserRepository


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/platform/auth/login",
)
optional_bearer = HTTPBearer(auto_error=False)


def _tenant_unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Tenant authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_platform_admin(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> PlatformAdmin:
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.type != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    repository = PlatformAdminRepository(db)
    admin = repository.get_by_id(payload.sub)

    if admin is None or not admin.is_active or admin.locked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return admin


def allow_platform_user(
    user: PlatformAdmin = Depends(get_current_platform_admin),
) -> PlatformAdmin:
    return user


def require_platform_admin(
    user: PlatformAdmin = Depends(get_current_platform_admin),
) -> PlatformAdmin:
    if user.role != PlatformAdminRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access required.",
        )
    return user


def get_current_tenant_user(
    request: Request,
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(get_db),
) -> TenantUser:
    token = request.cookies.get(settings.tenant_session_cookie_name)
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials

    if not token:
        raise _tenant_unauthorized()

    try:
        payload = decode_tenant_access_token(token)
    except ValueError:
        raise _tenant_unauthorized()

    if payload.type != "tenant_user":
        raise _tenant_unauthorized()

    if payload.tenant_id != tenant_context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access forbidden.",
        )

    user = TenantUserRepository(db).get_by_id(payload.sub)
    if (
        user is None
        or not user.is_active
        or user.locked
        or user.tenant_id != tenant_context.tenant_id
    ):
        raise _tenant_unauthorized()

    return user


def allow_tenant_user(
    user: TenantUser = Depends(get_current_tenant_user),
) -> TenantUser:
    return user


def require_tenant_admin(
    user: TenantUser = Depends(get_current_tenant_user),
) -> TenantUser:
    if user.role != TenantUserRole.TENANT_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator access required.",
        )

    return user


get_current_tenant_admin = require_tenant_admin


# Placeholder for connector authentication.
def get_current_connector():
    raise NotImplementedError
