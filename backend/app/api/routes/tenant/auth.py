from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app.api.auth import get_current_tenant_user
from app.api.dependencies import (
    get_oidc_authentication_service,
    get_oidc_user_service,
    get_tenant_account_activation_service,
    get_tenant_oidc_auth_session_service,
    get_tenant_local_authentication_service,
    get_tenant_user_management_service,
    get_tenant_sso_service,
)
from app.api.tenant_context import get_current_tenant_context
from app.core.exceptions import (
    OIDCAuthenticationError,
    OIDCAuthSessionError,
    OIDCConfigurationError,
    TenantAuthenticationError,
    TenantInviteError,
)
from app.core.security import create_tenant_access_token
from app.core.tenant_session import (
    clear_tenant_session_cookie,
    set_tenant_session_cookie,
)
from app.core.tenant_context import TenantContext
from app.core.url_builder import build_tenant_dashboard_path
from app.models.tenant_user import TenantUser
from app.schemas.tenant_auth import (
    TenantAdminSetupRequest,
    TenantAuthResult,
    TenantLocalLoginRequest,
    TenantMeResponse,
    TenantChangePasswordRequest,
)
from app.services.tenant_account_activation_service import TenantAccountActivationService
from app.services.oidc_authentication_service import OIDCAuthenticationService
from app.services.oidc_authorization_service import OIDCAuthorizationService
from app.services.oidc_user_service import OIDCUserService
from app.services.tenant_oidc_auth_session_service import (
    TenantOIDCAuthSessionService,
)
from app.services.tenant_local_authentication_service import (
    TenantLocalAuthenticationService,
)
from app.services.tenant_sso_service import TenantSSOService
from app.services.tenant_user_management_service import TenantUserManagementError, TenantUserManagementService


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
    response_model=TenantAuthResult,
)
def activate_tenant_admin(
    payload: TenantAdminSetupRequest,
    response: Response,
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    service: TenantAccountActivationService = Depends(
        get_tenant_account_activation_service
    ),
):
    try:
        user = service.activate(
            token=payload.token,
            password=payload.password,
            expected_tenant_id=tenant_context.tenant_id,
        )
    except TenantInviteError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    token = create_tenant_access_token(
        subject=user.id,
        username=user.username or user.email,
        tenant_id=user.tenant_id,
    )
    set_tenant_session_cookie(response, token, tenant_context.slug)
    return TenantAuthResult()


@router.post("/local-login", response_model=TenantAuthResult)
def local_login(
    payload: TenantLocalLoginRequest,
    response: Response,
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    service: TenantLocalAuthenticationService = Depends(
        get_tenant_local_authentication_service
    ),
):
    try:
        user = service.authenticate(
            tenant_id=tenant_context.tenant_id,
            username=payload.username,
            password=payload.password,
        )
    except TenantAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    token = create_tenant_access_token(
        subject=user.id,
        username=user.username or user.email,
        tenant_id=user.tenant_id,
    )
    set_tenant_session_cookie(response, token, tenant_context.slug)
    return TenantAuthResult()


@router.get("/callback")
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

    response = RedirectResponse(
        url=build_tenant_dashboard_path(tenant_context.slug),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    set_tenant_session_cookie(response, access_token, tenant_context.slug)
    return response


@router.get("/me", response_model=TenantMeResponse)
def get_tenant_session_user(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(get_current_tenant_user),
) -> TenantMeResponse:
    return TenantMeResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        auth_source=user.auth_source,
        tenant_id=str(user.tenant_id),
        tenant_slug=tenant_context.slug,
        tenant_name=tenant_context.definition.display_name or tenant_context.slug,
        role=user.role,
        username=user.username,
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_tenant_user(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_tenant_session_cookie(response, tenant_context.slug)
    return response


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_tenant_password(payload: TenantChangePasswordRequest, user: TenantUser = Depends(get_current_tenant_user), service: TenantUserManagementService = Depends(get_tenant_user_management_service)) -> Response:
    try:
        service.change_password(user, payload.current_password, payload.new_password)
    except TenantUserManagementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)
