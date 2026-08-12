from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.auth import allow_platform_user
from app.api.dependencies import get_platform_admin_service, get_platform_user_service
from app.models.platform_admin import PlatformAdmin
from app.core.security import create_access_token
from app.schemas.platform_auth import (
    PlatformChangePasswordRequest,
    PlatformLoginRequest,
    PlatformPasswordResetRequest,
    PlatformTokenResponse,
    PlatformUserResponse,
)
from app.services.platform_admin_service import PlatformAdminService
from app.services.platform_user_service import PlatformUserError, PlatformUserService


router = APIRouter(prefix="/platform/auth")

INVALID_LOGIN_MESSAGE = (
    "Invalid username or password. Too many unsuccessful sign-in attempts? "
    "If you have forgotten your password, contact your PEKA administrator."
)


@router.post("/login", response_model=PlatformTokenResponse)
def login(
    payload: PlatformLoginRequest,
    service: PlatformAdminService = Depends(get_platform_admin_service),
):
    admin = service.authenticate(payload.username, payload.password)

    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_LOGIN_MESSAGE,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        subject=admin.id,
        username=admin.username,
    )

    return PlatformTokenResponse(access_token=token)


@router.get("/me", response_model=PlatformUserResponse)
def me(user: PlatformAdmin = Depends(allow_platform_user)):
    return user


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: PlatformPasswordResetRequest,
    service: PlatformUserService = Depends(get_platform_user_service),
) -> Response:
    try:
        service.consume_reset(payload.token, payload.new_password)
    except PlatformUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PlatformChangePasswordRequest,
    user: PlatformAdmin = Depends(allow_platform_user),
    service: PlatformUserService = Depends(get_platform_user_service),
) -> Response:
    try:
        service.change_password(user, payload.current_password, payload.new_password)
    except PlatformUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)
