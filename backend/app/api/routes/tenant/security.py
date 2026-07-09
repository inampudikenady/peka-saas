from fastapi import APIRouter, Depends

from app.api.dependencies import get_tenant_sso_service
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.schemas.tenant_sso import (
    TenantSSOConfigResponse,
    TenantSSOConfigUpdate,
)
from app.services.tenant_sso_service import TenantSSOService

router = APIRouter(prefix="/tenant/admin/security")


@router.get(
    "/sso",
    response_model=TenantSSOConfigResponse,
)
def get_sso_configuration(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    service: TenantSSOService = Depends(get_tenant_sso_service),
):
    return service.get(tenant_context.tenant_id)


@router.put(
    "/sso",
    response_model=TenantSSOConfigResponse,
)
def update_sso_configuration(
    payload: TenantSSOConfigUpdate,
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    service: TenantSSOService = Depends(get_tenant_sso_service),
):
    return service.upsert(
        tenant_context.tenant_id,
        payload,
    )
