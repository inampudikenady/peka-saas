import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import (
    get_tenant_account_activation_service,
    get_tenant_sso_service,
)
from app.core.exceptions import TenantInviteError
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.schemas.tenant_auth import TenantAdminSetupRequest, TenantAuthResponse
from app.services.tenant_account_activation_service import TenantAccountActivationService
from app.services.oidc_authorization_service import OIDCAuthorizationService
from app.services.tenant_sso_service import TenantSSOService


router = APIRouter(prefix="/tenant/auth")


@router.get("/login")
def login_with_sso(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    sso_service: TenantSSOService = Depends(get_tenant_sso_service),
):
    config = sso_service.get(tenant_context.tenant_id)

    if config is None or not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO is not configured for this tenant.",
        )

    if not config.authorization_endpoint or not config.client_id or not config.redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO configuration is incomplete.",
        )

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    authorization_url = OIDCAuthorizationService().build_authorization_url(
        config=config,
        state=state,
        nonce=nonce,
    )

    return RedirectResponse(authorization_url)


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
