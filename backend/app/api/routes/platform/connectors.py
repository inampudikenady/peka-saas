from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import allow_platform_user
from app.api.dependencies import get_connector_service
from app.models.platform_admin import PlatformAdmin
from app.schemas.connector_api import ConnectorDetailResponse, ConnectorSummaryResponse
from app.services.connector_service import ConnectorService, ConnectorServiceError


router = APIRouter(prefix="/platform/connectors")


@router.get("", response_model=list[ConnectorSummaryResponse])
def list_connectors(
    current_user: PlatformAdmin = Depends(allow_platform_user),
    service: ConnectorService = Depends(get_connector_service),
):
    return service.list_platform_connectors()


@router.get("/{connector_id}", response_model=ConnectorDetailResponse)
def connector_detail(
    connector_id: UUID,
    current_user: PlatformAdmin = Depends(allow_platform_user),
    service: ConnectorService = Depends(get_connector_service),
):
    try:
        return service.get_platform_detail(connector_id)
    except ConnectorServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

