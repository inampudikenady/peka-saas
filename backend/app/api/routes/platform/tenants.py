from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_tenant_service
from app.schemas.tenant import TenantCreate, TenantResponse
from app.services.tenant_service import TenantService


router = APIRouter(prefix="/platform/tenants")


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant(
    payload: TenantCreate,
    service: TenantService = Depends(get_tenant_service),
):
    return service.create(payload)


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    service: TenantService = Depends(get_tenant_service),
):
    return service.list_active()


@router.get("/{slug}", response_model=TenantResponse)
def get_tenant(
    slug: str,
    service: TenantService = Depends(get_tenant_service),
):
    return service.get_by_slug_or_raise(slug)
