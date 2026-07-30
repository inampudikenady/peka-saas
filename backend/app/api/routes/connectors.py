"""Public, versioned endpoints called by customer connector appliances."""

from typing import Any
from uuid import UUID

import json
import re
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.dependencies import get_connector_service
from app.core.config import settings
from app.db.session import get_db
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import (
    ConnectorDocumentAcknowledgement,
    ConnectorDocumentMetadata,
    ConnectorDocumentStatus,
    DocumentErrorCode,
    DocumentErrorResponse,
)
from app.services.document_ingestion_service import DocumentIngestionError, DocumentIngestionService
from app.services.provider_factory import object_storage
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
            connector_id, header_connector_id, _bearer_secret(authorization),
            retired_status_code=403 if for_document_delivery else 401,
            reject_authentication_failed=for_document_delivery,
        )
    except ConnectorServiceError as exc:
        _raise_service_error(exc)


def _document_error_response(
    code: DocumentErrorCode, message: str, status_code: int
) -> JSONResponse:
    body = DocumentErrorResponse(code=code, message=message)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


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
    if request.method == "POST" and request.url.path == f"{settings.api_prefix}/connectors/register":
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
    if request.method == "POST" and re.fullmatch(
        rf"{re.escape(settings.api_prefix)}/connectors/[^/]+/documents",
        request.url.path,
    ):
        return _document_error_response(
            DocumentErrorCode.VALIDATION_FAILED,
            "The connector document request is invalid.", 422,
        )
    return await request_validation_exception_handler(request, exc)


async def _document_request_parts(
    request: Request,
) -> tuple[str, UploadFile | None]:
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        metadata_part = form.get("metadata")
        file_part = form.get("file")
        if not isinstance(metadata_part, str):
            raise ValueError("Multipart metadata must be a text field")
        if file_part is not None and not isinstance(file_part, UploadFile):
            raise ValueError("Multipart file part is invalid")
        return metadata_part, file_part
    if content_type.startswith("application/json"):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("JSON document metadata must be an object")
        return json.dumps(payload), None
    raise ValueError("Unsupported document request content type")


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
        raise HTTPException(status_code=429, detail="Too many heartbeat requests.", headers={"Retry-After": "60"})
    try:
        return service.heartbeat(connector_id, x_peka_connector_id, _bearer_secret(authorization), payload)
    except ConnectorServiceError as exc:
        _raise_service_error(exc)


@router.post(
    "/{connector_id}/documents",
    response_model=ConnectorDocumentAcknowledgement,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": DocumentErrorResponse}, 403: {"model": DocumentErrorResponse},
        404: {"model": DocumentErrorResponse}, 409: {"model": DocumentErrorResponse},
        413: {"model": DocumentErrorResponse}, 422: {"model": DocumentErrorResponse},
        503: {"model": DocumentErrorResponse},
    },
)
async def accept_connector_document(
    connector_id: UUID,
    request: Request,
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(default=None, alias="X-PEKA-Connector-ID"),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
    connector_service: ConnectorService = Depends(get_connector_service),
    db: Session = Depends(get_db),
):
    logger.info("document_received", extra={"connector_id": str(connector_id)})
    try:
        connector = connector_service.authenticate(
            connector_id, x_peka_connector_id, _bearer_secret(authorization),
            retired_status_code=403, reject_authentication_failed=True,
        )
    except ConnectorServiceError as exc:
        if "retired" in str(exc).lower():
            return _document_error_response(
                DocumentErrorCode.CONNECTOR_RETIRED, "The connector is retired.", 403
            )
        return _document_error_response(
            DocumentErrorCode.INVALID_CONNECTOR, "Connector authentication failed.",
            exc.status_code,
        )
    logger.info(
        "Connector authenticated for document delivery",
        extra={"tenant_id": str(connector.tenant_id), "connector_id": str(connector.id)},
    )
    upload: UploadFile | None = None
    try:
        metadata, upload = await _document_request_parts(request)
    except (json.JSONDecodeError, ValueError):
        return _document_error_response(
            DocumentErrorCode.VALIDATION_FAILED,
            "The connector document request is invalid.", 422,
        )
    try:
        document_metadata = ConnectorDocumentMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        detail = str(exc).lower()
        error_code = DocumentErrorCode.INVALID_DOCUMENT_METADATA
        if "mime_type is not supported" in detail:
            error_code = DocumentErrorCode.MIME_MISMATCH
        elif "unsupported" in detail:
            error_code = DocumentErrorCode.UNSUPPORTED_FILE_TYPE
        elif "document_key" in detail or "relative_path" in detail:
            error_code = DocumentErrorCode.INVALID_DOCUMENT_KEY
        return _document_error_response(
            error_code,
            "The document metadata is invalid.", 422,
        )
    service = DocumentIngestionService(
        DocumentRepository(db), object_storage(), settings.peka_ingestion_max_upload_bytes,
        settings.peka_document_idempotency_hours,
    )
    try:
        return await run_in_threadpool(
            service.accept,
            connector, document_metadata, idempotency_key,
            upload.file if upload is not None else None,
            upload.content_type if upload is not None else None,
        )
    except DocumentIngestionError as exc:
        return _document_error_response(exc.code, str(exc), exc.status_code)
    except Exception as exc:
        logger.error(
            "Connector document acceptance failed safely (internal_reason=%s)",
            type(exc).__name__,
            extra={"tenant_id": str(connector.tenant_id),
                   "connector_id": str(connector.id),
                   "error_code": type(exc).__name__},
        )
        return _document_error_response(
            DocumentErrorCode.STORAGE_UNAVAILABLE,
            "The document could not be accepted because a required service is unavailable.",
            503,
        )
    finally:
        if upload is not None:
            await upload.close()


@router.get("/{connector_id}/documents/status", response_model=list[ConnectorDocumentStatus])
def connector_document_status(
    connector_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(default=None, alias="X-PEKA-Connector-ID"),
    connector_service: ConnectorService = Depends(get_connector_service),
    db: Session = Depends(get_db),
):
    connector = _authenticate_connector(
        connector_id, authorization, x_peka_connector_id, connector_service
    )
    repository = DocumentRepository(db)
    response: list[ConnectorDocumentStatus] = []
    for document in repository.list_documents(connector.tenant_id, include_deleted=True):
        if document.connector_id != connector.id:
            continue
        version = (
            repository.get_version(connector.tenant_id, document.current_version_id)
            if document.current_version_id else None
        )
        response.append(ConnectorDocumentStatus(
            document_id=document.id, version_id=version.id if version else None,
            content_hash=version.content_hash if version else None,
            ingestion_status=("DELETED" if document.is_deleted else version.ingestion_status.value if version else "RECEIVED"),
            error_code=version.error_code if version else None,
            error_message=version.safe_error_message if version else None,
            updated_at=document.updated_at,
        ))
        if len(response) >= limit:
            break
    return response


@router.get(
    "/{connector_id}/operational-tools/requests/next",
    response_model=OperationalToolRequestView,
    responses={204: {"description": "No pending request"}},
)
def claim_operational_tool_request(
    connector_id: UUID,
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(
        default=None, alias="X-PEKA-Connector-ID"
    ),
    connector_service: ConnectorService = Depends(get_connector_service),
    db: Session = Depends(get_db),
):
    connector = _authenticate_connector(
        connector_id, authorization, x_peka_connector_id, connector_service
    )
    request = OperationalToolService(db).claim(connector)
    return request if request is not None else Response(status_code=204)


@router.post(
    "/{connector_id}/operational-tools/requests/{request_id}/result",
    status_code=status.HTTP_204_NO_CONTENT,
)
def submit_operational_tool_result(
    connector_id: UUID,
    request_id: UUID,
    payload: OperationalToolResultSubmission,
    authorization: str | None = Header(default=None),
    x_peka_connector_id: str | None = Header(
        default=None, alias="X-PEKA-Connector-ID"
    ),
    connector_service: ConnectorService = Depends(get_connector_service),
    db: Session = Depends(get_db),
) -> Response:
    connector = _authenticate_connector(
        connector_id, authorization, x_peka_connector_id, connector_service
    )
    try:
        OperationalToolService(db).submit(connector, request_id, payload)
    except OperationalToolConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)
