import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_tenant_admin
from app.api.dependencies import get_tenant_sso_service
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.models.tenant_user import TenantUser
from app.schemas.tenant_sso import (
    TenantSSOConfigResponse,
    TenantSSOConfigUpdate,
    TenantSSOTestResponse,
)
from app.services.tenant_sso_service import TenantSSOService
from app.core.exceptions import OIDCConfigurationError
from app.core.logging import request_id_ctx

router = APIRouter(prefix="/tenant/admin/security")
logger = logging.getLogger(__name__)


@router.get(
    "/sso",
    response_model=TenantSSOConfigResponse,
)
def get_sso_configuration(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    tenant_admin: TenantUser = Depends(get_current_tenant_admin),
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
    tenant_admin: TenantUser = Depends(get_current_tenant_admin),
    service: TenantSSOService = Depends(get_tenant_sso_service),
):
    try:
        return service.upsert(
            tenant_context.tenant_id,
            payload,
        )
    except OIDCConfigurationError as exc:
        logger.warning(
            "Tenant SSO configuration validation failed",
            extra={
                "tenant_id": str(tenant_context.tenant_id),
                "provider": payload.provider.value,
                "failure_stage": "configuration_validation",
                "request_id": request_id_ctx.get(),
            },
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sso/test", response_model=TenantSSOTestResponse)
def test_sso_configuration(
    tenant_context: TenantContext = Depends(get_current_tenant_context),
    tenant_admin: TenantUser = Depends(get_current_tenant_admin),
    service: TenantSSOService = Depends(get_tenant_sso_service),
):
    try:
        return service.test_configuration(tenant_context.tenant_id)
    except OIDCConfigurationError as exc:
        logger.warning(
            "Tenant SSO configuration test failed",
            extra={
                "tenant_id": str(tenant_context.tenant_id),
                "failure_stage": "oidc_discovery_test",
                "request_id": request_id_ctx.get(),
            },
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
