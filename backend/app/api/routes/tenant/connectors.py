from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.auth import require_tenant_admin
from app.api.dependencies import get_connector_service
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.models.tenant_user import TenantUser
from app.schemas.connector_api import (
    ConnectorDetailResponse,
    ConnectorSummaryResponse,
    RegistrationTokenCreate,
    RegistrationTokenCreatedResponse,
    RegistrationTokenResponse,
)
from app.services.connector_service import ConnectorService, ConnectorServiceError


router = APIRouter(prefix="/tenant/connectors")


def handle(action):
    try:
        return action()
    except ConnectorServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("", response_model=list[ConnectorSummaryResponse])
def list_connectors(
    include_retired: bool = False,
    context: TenantContext = Depends(get_current_tenant_context),
    actor: TenantUser = Depends(require_tenant_admin),
    service: ConnectorService = Depends(get_connector_service),
):
    return service.list_tenant_connectors(context.tenant_id, include_retired=include_retired)


@router.get("/registration-tokens", response_model=list[RegistrationTokenResponse])
def list_registration_tokens(
    include_inactive: bool = False,
    context: TenantContext = Depends(get_current_tenant_context),
    actor: TenantUser = Depends(require_tenant_admin),
    service: ConnectorService = Depends(get_connector_service),
):
    return service.list_registration_tokens(context.tenant_id, include_inactive=include_inactive)


@router.post("/registration-tokens", response_model=RegistrationTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_registration_token(
    _payload: RegistrationTokenCreate | None = None,
    context: TenantContext = Depends(get_current_tenant_context),
    actor: TenantUser = Depends(require_tenant_admin),
    service: ConnectorService = Depends(get_connector_service),
):
    return service.create_registration_token(context.tenant_id, actor, None)


@router.delete("/registration-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_registration_token(
    token_id: UUID,
    context: TenantContext = Depends(get_current_tenant_context),
    actor: TenantUser = Depends(require_tenant_admin),
    service: ConnectorService = Depends(get_connector_service),
) -> Response:
    handle(lambda: service.revoke_registration_token(context.tenant_id, token_id, actor))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{connector_id}", response_model=ConnectorDetailResponse)
def connector_detail(
    connector_id: UUID,
    context: TenantContext = Depends(get_current_tenant_context),
    actor: TenantUser = Depends(require_tenant_admin),
    service: ConnectorService = Depends(get_connector_service),
):
    return handle(lambda: service.get_tenant_detail(context.tenant_id, connector_id))


@router.post("/{connector_id}/retire", response_model=ConnectorDetailResponse)
def retire_connector(
    connector_id: UUID,
    context: TenantContext = Depends(get_current_tenant_context),
    actor: TenantUser = Depends(require_tenant_admin),
    service: ConnectorService = Depends(get_connector_service),
):
    return handle(lambda: service.retire(context.tenant_id, connector_id, actor))
