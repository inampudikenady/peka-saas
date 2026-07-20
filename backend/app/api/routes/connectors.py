"""Public, versioned endpoints called by customer connector appliances."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.api.dependencies import get_connector_service
from app.core.rate_limit import heartbeat_limiter, registration_limiter
from app.schemas.connector_api import (
    ConnectorHeartbeatRequest,
    ConnectorHeartbeatResponse,
    ConnectorRegistrationRequest,
    ConnectorRegistrationResponse,
)
from app.services.connector_service import ConnectorService, ConnectorServiceError


router = APIRouter(prefix="/connectors")


def _raise_service_error(exc: ConnectorServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _bearer_secret(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credentials = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credentials:
        return None
    return credentials


@router.post("/register", response_model=ConnectorRegistrationResponse, status_code=status.HTTP_201_CREATED)
def register_connector(
    payload: ConnectorRegistrationRequest,
    request: Request,
    service: ConnectorService = Depends(get_connector_service),
):
    client = request.client.host if request.client else "unknown"
    if not registration_limiter.allow(client):
        raise HTTPException(status_code=429, detail="Too many connector registration attempts.", headers={"Retry-After": "300"})
    try:
        return service.register(payload)
    except ConnectorServiceError as exc:
        _raise_service_error(exc)


@router.post("/{connector_id}/heartbeat", response_model=ConnectorHeartbeatResponse)
def connector_heartbeat(
    connector_id: UUID,
    payload: ConnectorHeartbeatRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(default=None, alias="X-PEKA-Connector-ID"),
    service: ConnectorService = Depends(get_connector_service),
):
    client = request.client.host if request.client else "unknown"
    if not heartbeat_limiter.allow(f"{client}:{connector_id}"):
        raise HTTPException(status_code=429, detail="Too many heartbeat requests.", headers={"Retry-After": "60"})
    try:
        return service.heartbeat(connector_id, x_peka_connector_id, _bearer_secret(authorization), payload)
    except ConnectorServiceError as exc:
        _raise_service_error(exc)

