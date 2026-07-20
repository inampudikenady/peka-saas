from fastapi import APIRouter, Depends, HTTPException, Response, status
from app.api.auth import allow_platform_user, require_platform_admin
from app.models.platform_admin import PlatformAdmin

from app.api.dependencies import (
    get_tenant_admin_invite_service,
    get_tenant_platform_summary_service,
    get_tenant_service,
)
from app.core.exceptions import TenantLifecycleError
from app.schemas.tenant import (
    TenantAdminInviteResponse,
    TenantCreate,
    TenantCreateResponse,
    TenantPlatformSummary,
    TenantResponse,
)
from app.services.tenant_admin_invite_service import TenantAdminInviteService
from app.services.tenant_platform_summary_service import TenantPlatformSummaryService
from app.services.tenant_service import TenantService


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
    return service.create(payload)


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
    return service.set_active(slug, active=False)


@router.post("/{slug}/activate", response_model=TenantResponse)
def activate_tenant(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
):
    return service.set_active(slug, active=True)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    slug: str,
    confirmation: str,
    service: TenantService = Depends(get_tenant_service),
    current_admin: PlatformAdmin = Depends(require_platform_admin),
) -> Response:
    try:
        service.delete(slug, confirmation)
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
