import logging

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
    OIDCUserAuthorizationError,
    TenantAuthenticationError,
    TenantInviteError,
)
from app.core.security import create_tenant_access_token
from app.core.logging import request_id_ctx
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
from app.schemas.tenant_sso import TenantSSOLoginOptions
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
logger = logging.getLogger(__name__)


@router.get("/sso-options", response_model=TenantSSOLoginOptions)
def sso_login_options(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    sso_service: TenantSSOService = Depends(get_tenant_sso_service),
) -> TenantSSOLoginOptions:
    config = sso_service.get(tenant_context.tenant_id)
    return TenantSSOLoginOptions(
        provider=config.provider if config else None,
        enabled=bool(config and config.enabled),
    )


@router.get("/login")
def login_with_sso(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    sso_service: TenantSSOService = Depends(get_tenant_sso_service),
    auth_session_service: TenantOIDCAuthSessionService = Depends(
        get_tenant_oidc_auth_session_service
    ),
):
    try:
        config = sso_service.resolve_for_authentication(tenant_context.tenant_id)
    except OIDCConfigurationError as exc:
        logger.warning(
            "OIDC login initiation failed",
            extra={
                "tenant_id": str(tenant_context.tenant_id),
                "failure_stage": "discovery",
                "request_id": request_id_ctx.get(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    auth_session, raw_state = auth_session_service.create(
        tenant_id=tenant_context.tenant_id,
        redirect_uri=config.redirect_uri,
    )
    assert auth_session.code_verifier is not None

    authorization_url = OIDCAuthorizationService().build_authorization_url(
        config=config,
        state=raw_state,
        nonce=auth_session.nonce,
        code_challenge=auth_session_service.code_challenge(
            auth_session.code_verifier
        ),
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
    state: str,
    code: str | None = None,
    error: str | None = None,
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

    auth_session_service.consume(session)

    if error:
        logger.warning(
            "OIDC provider rejected login",
            extra={
                "tenant_id": str(tenant_context.tenant_id),
                "failure_stage": "provider_authorization",
                "provider_error_code": error[:100],
                "request_id": request_id_ctx.get(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identity provider rejected the login.",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identity provider did not return an authorization code.",
        )

    try:
        config = sso_service.resolve_for_authentication(
            tenant_context.tenant_id
        )
        identity = authentication_service.authenticate(
            config=config,
            code=code,
            expected_nonce=session.nonce,
            redirect_uri=session.redirect_uri,
            code_verifier=session.code_verifier,
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

    try:
        user = oidc_user_service.provision(
            tenant_id=tenant_context.tenant_id,
            identity=identity,
        )
    except OIDCUserAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

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
