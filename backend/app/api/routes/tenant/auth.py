from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_tenant_account_activation_service
from app.core.exceptions import TenantInviteError
from app.schemas.tenant_auth import TenantAdminSetupRequest, TenantAuthResponse
from app.services.tenant_account_activation_service import TenantAccountActivationService


router = APIRouter(prefix="/tenant/auth")


@router.post(
    "/activate",
    response_model=TenantAuthResponse,
)
def activate_tenant_admin(
    payload: TenantAdminSetupRequest,
    service: TenantAccountActivationService = Depends(
        get_tenant_account_activation_service
    ),
):
    try:
        return service.activate(
            token=payload.token,
            password=payload.password,
        )
    except TenantInviteError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
