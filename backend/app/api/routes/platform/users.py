from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_platform_admin
from app.api.dependencies import get_platform_user_service
from app.models.platform_admin import PlatformAdmin
from app.schemas.platform_auth import PlatformInvitationResponse, PlatformUserCreate, PlatformUserResponse, PlatformUserUpdate
from app.services.platform_user_service import PlatformUserError, PlatformUserService

router = APIRouter(prefix="/platform/users")


def handle(action):
    try:
        return action()
    except PlatformUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[PlatformUserResponse])
def list_users(service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return service.list()


@router.post("", response_model=PlatformInvitationResponse, status_code=201)
def create_user(payload: PlatformUserCreate, service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return handle(lambda: service.create(payload, actor))


@router.get("/{user_id}", response_model=PlatformUserResponse)
def get_user(user_id: UUID, service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return handle(lambda: service.get(user_id))


@router.put("/{user_id}", response_model=PlatformUserResponse)
def update_user(user_id: UUID, payload: PlatformUserUpdate, service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return handle(lambda: service.update(user_id, payload, actor))


@router.post("/{user_id}/activate", response_model=PlatformUserResponse)
def activate_user(user_id: UUID, service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return handle(lambda: service.set_active(user_id, True, actor))


@router.post("/{user_id}/deactivate", response_model=PlatformUserResponse)
def deactivate_user(user_id: UUID, service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return handle(lambda: service.set_active(user_id, False, actor))


@router.post("/{user_id}/password-reset", response_model=PlatformInvitationResponse)
def password_reset(user_id: UUID, service: PlatformUserService = Depends(get_platform_user_service), actor: PlatformAdmin = Depends(require_platform_admin)):
    return handle(lambda: service.password_reset(user_id, actor))
