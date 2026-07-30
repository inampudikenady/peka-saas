from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from app.api.auth import allow_platform_user, require_platform_admin
from app.db.session import get_db
from app.models.platform_admin import PlatformAdmin
from app.models.tenant_user import TenantUserRole
from app.repositories.tenant_user_repository import TenantUserRepository

from app.api.dependencies import (
    get_tenant_admin_invite_service,
    get_tenant_platform_summary_service,
    get_tenant_service,
    get_tenant_password_reset_service,
)
from app.core.exceptions import TenantLifecycleError
from app.schemas.tenant import (
    TenantAdminInviteResponse,
    TenantAdminInviteUpdate,
    TenantAdministratorResponse,
    TenantAuditEventResponse,
    TenantCreate,
    TenantCreateResponse,
    TenantPlatformSummary,
    TenantResponse,
    TenantUpdate,
)
from app.services.tenant_admin_invite_service import TenantAdminInviteService
from app.services.tenant_platform_summary_service import TenantPlatformSummaryService
from app.services.tenant_service import TenantService
from app.services.tenant_password_reset_service import (
    TenantPasswordResetError,
    TenantPasswordResetService,
)


router = APIRouter(prefix="/platform/tenants")


@router.post(
    "",
    response_model=TenantCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant(
    payload: TenantCreate,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    return service.create(payload, current_admin)


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(allow_platform_user),
):
    return service.list_active()


@router.get("/{slug}", response_model=TenantResponse)
def get_tenant(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(allow_platform_user),
):
    return service.get_by_slug_or_raise(slug)


@router.patch("/{slug}", response_model=TenantResponse)
def update_tenant(
    slug: str,
    payload: TenantUpdate,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    return service.update(slug, payload, current_admin)


@router.get("/{slug}/summary", response_model=TenantPlatformSummary)
def get_tenant_summary(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    summary_service: TenantPlatformSummaryService = Depends(
        get_tenant_platform_summary_service
    ),
    current_admin: PlatformAdmin = Depends(allow_platform_user),
):
    return summary_service.get(service.get_by_slug_or_raise(slug))


@router.post("/{slug}/deactivate", response_model=TenantResponse)
def deactivate_tenant(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    try:
        return service.set_active(slug, active=False, actor=current_admin)
    except TenantLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{slug}/activate", response_model=TenantResponse)
def activate_tenant(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    try:
        return service.set_active(slug, active=True, actor=current_admin)
    except TenantLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    slug: str,
    confirmation: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
) -> Response:
    try:
        service.delete(slug, confirmation, current_admin)
    except TenantLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{slug}/admin-invite",
    response_model=TenantAdminInviteResponse | None,
)
def get_tenant_admin_invite(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    invite_service: TenantAdminInviteService = Depends(
        get_tenant_admin_invite_service
    ),
    current_admin: PlatformAdmin = Depends(allow_platform_user),
):
    return invite_service.get_status(service.get_by_slug_or_raise(slug))


@router.patch(
    "/{slug}/admin-invite",
    response_model=TenantAdminInviteResponse,
)
def update_tenant_admin_invite(
    slug: str,
    payload: TenantAdminInviteUpdate,
    service: TenantService = Depends(get_tenant_service),
    invite_service: TenantAdminInviteService = Depends(get_tenant_admin_invite_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    try:
        return invite_service.update_recipient(
            service.get_by_slug_or_raise(slug),
            payload.email,
            payload.full_name,
            current_admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{slug}/administrators",
    response_model=list[TenantAdministratorResponse],
)
def list_tenant_administrators(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    db: Session = Depends(get_db),
    current_admin: PlatformAdmin = Depends(allow_platform_user),
):
    tenant = service.get_by_slug_or_raise(slug)
    return [
        user for user in TenantUserRepository(db).list_for_tenant(tenant.id)
        if user.role == TenantUserRole.TENANT_ADMIN
    ]


@router.post(
    "/{slug}/administrators/{user_id}/password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
)
def send_tenant_administrator_password_reset(
    slug: str,
    user_id: UUID,
    service: TenantService = Depends(get_tenant_service),
    reset_service: TenantPasswordResetService = Depends(
        get_tenant_password_reset_service
    ),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
) -> Response:
    try:
        reset_service.request_by_platform_admin(
            service.get_by_slug_or_raise(slug), user_id, current_admin
        )
    except TenantPasswordResetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{slug}/audit-events",
    response_model=list[TenantAuditEventResponse],
)
def list_tenant_audit_events(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(allow_platform_user),
):
    return service.list_audit_events(slug)


@router.post(
    "/{slug}/admin-invite/regenerate",
    response_model=TenantAdminInviteResponse,
)
def regenerate_tenant_admin_invite(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    invite_service: TenantAdminInviteService = Depends(
        get_tenant_admin_invite_service
    ),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    try:
        return invite_service.regenerate(
            tenant=service.get_by_slug_or_raise(slug),
            created_by_platform_admin_id=current_admin.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
