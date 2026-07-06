from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.platform_admin import PlatformAdmin
from app.repositories.platform_admin_repository import PlatformAdminRepository


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/platform/auth/login",
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


# Placeholder for future authentication providers.
def get_current_tenant_user():
    raise NotImplementedError


# Placeholder for connector authentication.
def get_current_connector():
    raise NotImplementedError