from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import (
    get_oidc_authentication_service,
    get_oidc_user_service,
    get_tenant_account_activation_service,
    get_tenant_oidc_auth_session_service,
    get_tenant_sso_service,
)
from app.api.tenant_context import get_current_tenant_context
from app.core.exceptions import (
    OIDCAuthenticationError,
    OIDCAuthSessionError,
    OIDCConfigurationError,
    TenantInviteError,
)
from app.core.security import create_tenant_access_token
from app.core.tenant_context import TenantContext
from app.schemas.tenant_auth import TenantAdminSetupRequest, TenantAuthResponse
from app.services.tenant_account_activation_service import TenantAccountActivationService
from app.services.oidc_authentication_service import OIDCAuthenticationService
from app.services.oidc_authorization_service import OIDCAuthorizationService
from app.services.oidc_user_service import OIDCUserService
from app.services.tenant_oidc_auth_session_service import (
    TenantOIDCAuthSessionService,
)
from app.services.tenant_sso_service import TenantSSOService


router = APIRouter(prefix="/tenant/auth")


@router.get("/login")
def login_with_sso(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    sso_service: TenantSSOService = Depends(get_tenant_sso_service),
    auth_session_service: TenantOIDCAuthSessionService = Depends(
        get_tenant_oidc_auth_session_service
    ),
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

    auth_session, raw_state = auth_session_service.create(
        tenant_id=tenant_context.tenant_id,
        redirect_uri=config.redirect_uri,
    )

    authorization_url = OIDCAuthorizationService().build_authorization_url(
        config=config,
        state=raw_state,
        nonce=auth_session.nonce,
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


@router.get("/callback", response_model=TenantAuthResponse)
def oidc_callback(
    code: str,
    state: str,
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    sso_service: TenantSSOService = Depends(get_tenant_sso_service),
    auth_session_service: TenantOIDCAuthSessionService = Depends(
        get_tenant_oidc_auth_session_service
    ),
    authentication_service: OIDCAuthenticationService = Depends(
        get_oidc_authentication_service
    ),
    oidc_user_service: OIDCUserService = Depends(
        get_oidc_user_service
    ),
):
    try:
        session = auth_session_service.validate(
            raw_state=state,
            tenant_id=tenant_context.tenant_id,
        )
    except OIDCAuthSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    config = sso_service.get(tenant_context.tenant_id)

    if config is None or not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO is not configured.",
        )

    try:
        identity = authentication_service.authenticate(
            config=config,
            code=code,
            expected_nonce=session.nonce,
        )
    except OIDCConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except OIDCAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user = oidc_user_service.provision(
        tenant_id=tenant_context.tenant_id,
        identity=identity,
    )

    auth_session_service.consume(session)

    access_token = create_tenant_access_token(
        subject=user.id,
        username=user.username or user.email,
        tenant_id=user.tenant_id,
    )

    return TenantAuthResponse(access_token=access_token)
