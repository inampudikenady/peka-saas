from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_tenant_admin
from app.api.dependencies import get_tenant_user_management_service
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.models.tenant_user import TenantUser
from app.schemas.tenant_user import TenantUserCreate, TenantUserInvitationResponse, TenantUserResponse, TenantUserRoleUpdate
from app.services.tenant_user_management_service import TenantUserManagementError, TenantUserManagementService

router = APIRouter(prefix="/tenant/admin/users")


def handle(action):
    try:
        return action()
    except TenantUserManagementError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[TenantUserResponse])
def list_users(context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return service.list(context.tenant_id)


@router.post("", response_model=TenantUserInvitationResponse, status_code=201)
def create_user(payload: TenantUserCreate, context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return handle(lambda: service.create(context.tenant_id, payload, actor))


@router.get("/{user_id}", response_model=TenantUserResponse)
def get_user(user_id: UUID, context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return handle(lambda: service.get(context.tenant_id, user_id))


@router.put("/{user_id}/role", response_model=TenantUserResponse)
def set_role(user_id: UUID, payload: TenantUserRoleUpdate, context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return handle(lambda: service.set_role(context.tenant_id, user_id, payload.role, actor))


@router.post("/{user_id}/activate", response_model=TenantUserResponse)
def activate(user_id: UUID, context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return handle(lambda: service.set_active(context.tenant_id, user_id, True, actor))


@router.post("/{user_id}/deactivate", response_model=TenantUserResponse)
def deactivate(user_id: UUID, context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return handle(lambda: service.set_active(context.tenant_id, user_id, False, actor))


@router.post("/{user_id}/password-reset", response_model=TenantUserInvitationResponse)
def password_reset(user_id: UUID, context: TenantContext = Depends(get_current_tenant_context), actor: TenantUser = Depends(require_tenant_admin), service: TenantUserManagementService = Depends(get_tenant_user_management_service)):
    return handle(lambda: service.reset(context.tenant_id, user_id, actor))
