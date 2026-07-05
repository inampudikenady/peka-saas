from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_platform_admin_service
from app.core.security import create_access_token
from app.schemas.platform_auth import PlatformLoginRequest, PlatformTokenResponse
from app.services.platform_admin_service import PlatformAdminService


router = APIRouter(prefix="/platform/auth")


@router.post("/login", response_model=PlatformTokenResponse)
def login(
    payload: PlatformLoginRequest,
    service: PlatformAdminService = Depends(get_platform_admin_service),
):
    admin = service.authenticate(payload.username, payload.password)

    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token = create_access_token(
        subject=admin.id,
        username=admin.username,
    )

    return PlatformTokenResponse(access_token=token)
