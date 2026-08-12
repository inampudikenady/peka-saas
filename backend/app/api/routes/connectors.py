"""Public, versioned endpoints called by customer connector appliances."""

from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import get_connector_service
from app.core.config import settings
from app.core.logging import connector_id_ctx, tenant_id_ctx
from app.core.tenant_context import TenantContext
from app.core.tenant_definition import TenantDefinition
from app.db.session import get_db
from app.models.connector import ManagedConnector
from sqlalchemy.orm import Session
from app.core.connector_registration_diagnostics import (
    log_registration_completed,
    log_registration_received,
    log_registration_rejected,
)
from app.core.rate_limit import heartbeat_limiter, registration_limiter
from app.schemas.connector_api import (
    ConnectorHeartbeatRequest,
    ConnectorHeartbeatResponse,
    ConnectorRegistrationErrorCode,
    ConnectorRegistrationErrorResponse,
    ConnectorRegistrationRequest,
    ConnectorRegistrationResponse,
)
from app.services.connector_service import (
    ConnectorRegistrationError,
    ConnectorService,
    ConnectorServiceError,
)
from app.schemas.operational_tools import (
    OperationalToolRequestView,
    OperationalToolResultSubmission,
)
from app.services.operational_tool_service import (
    OperationalToolConflict,
    OperationalToolService,
)


router = APIRouter(prefix="/connectors")
logger = logging.getLogger(__name__)


def _raise_service_error(exc: ConnectorServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _bearer_secret(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credentials = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credentials:
        return None
    return credentials


def _authenticate_connector(
    connector_id: UUID,
    authorization: str | None,
    header_connector_id: str | None,
    service: ConnectorService,
    *,
    for_document_delivery: bool = False,
):
    try:
        return service.authenticate(
            connector_id,
            header_connector_id,
            _bearer_secret(authorization),
            retired_status_code=403 if for_document_delivery else 401,
            reject_authentication_failed=for_document_delivery,
        )
    except ConnectorServiceError as exc:
        _raise_service_error(exc)


@contextmanager
def _connector_request_context(
    request: Request,
    connector: ManagedConnector,
    service: ConnectorService,
) -> Iterator[None]:
    """Bind tenant identity derived exclusively from an authenticated connector."""
    tenant = service.tenant_repository.get_by_id(connector.tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector tenant no longer exists.",
        )

    definition = TenantDefinition(
        tenant_id=tenant.id,
        slug=tenant.slug,
        hostname=tenant.primary_domain or "",
        enabled=tenant.status.value == "active",
        display_name=tenant.display_name,
        timezone=tenant.timezone,
    )
    request.state.tenant_context = TenantContext(
        tenant_id=tenant.id,
        slug=tenant.slug,
        hostname=definition.hostname,
        definition=definition,
    )
    request.state.tenant_id = tenant.id
    request.state.connector_id = connector.id

    tenant_token = tenant_id_ctx.set(str(tenant.id))
    connector_token = connector_id_ctx.set(str(connector.id))
    try:
        yield
    finally:
        connector_id_ctx.reset(connector_token)
        tenant_id_ctx.reset(tenant_token)


def _registration_error_response(
    code: ConnectorRegistrationErrorCode,
    message: str,
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ConnectorRegistrationErrorResponse(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def _validated_instance_id(body: Any) -> UUID | None:
    if not isinstance(body, dict):
        return None
    try:
        return UUID(str(body.get("instance_id")))
    except (TypeError, ValueError, AttributeError):
        return None


async def connector_registration_validation_handler(
    request: Request,
    exc: RequestValidationError,
):
    if (
        request.method == "POST"
        and request.url.path == f"{settings.api_prefix}/connectors/register"
    ):
        instance_id = _validated_instance_id(exc.body)
        log_registration_received(request, instance_id)
        log_registration_rejected(
            request,
            ConnectorRegistrationErrorCode.VALIDATION_FAILED,
            instance_id=instance_id,
            internal_reason="request_validation_failed",
        )
        return _registration_error_response(
            ConnectorRegistrationErrorCode.VALIDATION_FAILED,
            "The connector registration request is invalid.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return await request_validation_exception_handler(request, exc)


@router.post(
    "/register",
    response_model=ConnectorRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ConnectorRegistrationErrorResponse},
        403: {"model": ConnectorRegistrationErrorResponse},
        409: {"model": ConnectorRegistrationErrorResponse},
        410: {"model": ConnectorRegistrationErrorResponse},
        422: {"model": ConnectorRegistrationErrorResponse},
        429: {"model": ConnectorRegistrationErrorResponse},
        500: {"model": ConnectorRegistrationErrorResponse},
    },
)
def register_connector(
    payload: ConnectorRegistrationRequest,
    request: Request,
    service: ConnectorService = Depends(get_connector_service),
):
    log_registration_received(request, payload.instance_id)
    client = request.client.host if request.client else "unknown"
    if not registration_limiter.allow(client):
        log_registration_rejected(
            request,
            ConnectorRegistrationErrorCode.RATE_LIMITED,
            instance_id=payload.instance_id,
            internal_reason="registration_rate_limit_exceeded",
        )
        return _registration_error_response(
            ConnectorRegistrationErrorCode.RATE_LIMITED,
            "Too many connector registration attempts.",
            status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": "300"},
        )
    try:
        response = service.register(payload)
    except ConnectorRegistrationError as exc:
        log_registration_rejected(
            request,
            exc.code,
            instance_id=payload.instance_id,
            tenant_id=exc.tenant_id,
            registration_token_id=exc.registration_token_id,
            internal_reason=exc.internal_reason,
        )
        return _registration_error_response(exc.code, str(exc), exc.status_code)
    except Exception as exc:
        log_registration_rejected(
            request,
            ConnectorRegistrationErrorCode.INTERNAL_ERROR,
            instance_id=payload.instance_id,
            internal_reason=f"unexpected_{type(exc).__name__}",
        )
        return _registration_error_response(
            ConnectorRegistrationErrorCode.INTERNAL_ERROR,
            "Connector registration failed unexpectedly.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    log_registration_completed(
        request,
        instance_id=payload.instance_id,
        tenant_id=response.tenant_id,
        registration_token_id=response._registration_token_id,
    )
    return response


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
        raise HTTPException(
            status_code=429,
            detail="Too many heartbeat requests.",
            headers={"Retry-After": "60"},
        )
    connector = _authenticate_connector(
        connector_id, authorization, x_peka_connector_id, service
    )
    with _connector_request_context(request, connector, service):
        try:
            return service.record_heartbeat(connector, payload)
        except ConnectorServiceError as exc:
            _raise_service_error(exc)


@router.get(
    "/{connector_id}/operational-tools/requests/next",
    response_model=OperationalToolRequestView,
    responses={204: {"description": "No pending request"}},
)
def claim_operational_tool_request(
    connector_id: UUID,
    http_request: Request,
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(default=None, alias="X-PEKA-Connector-ID"),
    connector_service: ConnectorService = Depends(get_connector_service),
    db: Session = Depends(get_db),
):
    connector = _authenticate_connector(
        connector_id, authorization, x_peka_connector_id, connector_service
    )
    with _connector_request_context(http_request, connector, connector_service):
        tool_request = OperationalToolService(db).claim(connector)
        return tool_request if tool_request is not None else Response(status_code=204)


@router.post(
    "/{connector_id}/operational-tools/requests/{request_id}/result",
    status_code=status.HTTP_204_NO_CONTENT,
)
def submit_operational_tool_result(
    connector_id: UUID,
    request_id: UUID,
    payload: OperationalToolResultSubmission,
    http_request: Request,
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(default=None, alias="X-PEKA-Connector-ID"),
    connector_service: ConnectorService = Depends(get_connector_service),
    db: Session = Depends(get_db),
) -> Response:
    connector = _authenticate_connector(
        connector_id, authorization, x_peka_connector_id, connector_service
    )
    with _connector_request_context(http_request, connector, connector_service):
        try:
            OperationalToolService(db).submit(connector, request_id, payload)
        except OperationalToolConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(status_code=204)
