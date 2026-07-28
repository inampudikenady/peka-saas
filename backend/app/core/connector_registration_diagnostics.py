"""Credential-safe structured diagnostics for connector registration."""

import logging
from uuid import UUID

from fastapi import Request

from app.core.logging import request_id_ctx
from app.schemas.connector_api import ConnectorRegistrationErrorCode


logger = logging.getLogger("app.connector_registration")

_REJECTION_EVENTS = {
    ConnectorRegistrationErrorCode.TOKEN_NOT_FOUND: "connector_registration_token_validation_failed",
    ConnectorRegistrationErrorCode.TOKEN_HASH_MISMATCH: "connector_registration_token_validation_failed",
    ConnectorRegistrationErrorCode.TOKEN_EXPIRED: "connector_registration_token_expired",
    ConnectorRegistrationErrorCode.TOKEN_USED: "connector_registration_token_already_used",
    ConnectorRegistrationErrorCode.TOKEN_REVOKED: "connector_registration_token_revoked",
    ConnectorRegistrationErrorCode.INSTANCE_ALREADY_REGISTERED: "connector_registration_duplicate_instance_detected",
    ConnectorRegistrationErrorCode.VALIDATION_FAILED: "connector_registration_validation_failed",
    ConnectorRegistrationErrorCode.TENANT_MISMATCH: "connector_registration_tenant_mismatch",
    ConnectorRegistrationErrorCode.TENANT_INACTIVE: "connector_registration_tenant_inactive",
    ConnectorRegistrationErrorCode.CONNECTOR_LIMIT_REACHED: "connector_registration_limit_reached",
    ConnectorRegistrationErrorCode.REGISTRATION_NOT_PERMITTED: "connector_registration_not_permitted",
    ConnectorRegistrationErrorCode.RATE_LIMITED: "connector_registration_rate_limited",
    ConnectorRegistrationErrorCode.INTERNAL_ERROR: "connector_registration_internal_error",
}


def _request_id(request: Request) -> str:
    context_id = request_id_ctx.get()
    value = context_id if context_id != "-" else request.headers.get("X-Request-ID", "-")
    return "".join(character if character.isprintable() and not character.isspace() else "_" for character in value)[:128]


def _value(value: UUID | str | None) -> str:
    return str(value) if value is not None else "-"


def _safe_reason(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in value
    )[:128]


def log_registration_received(request: Request, instance_id: UUID | str | None) -> None:
    logger.info(
        "connector_registration_request_received request_id=%s instance_id=%s "
        "tenant_id=- registration_token_id=- rejection_code=-",
        _request_id(request),
        _value(instance_id),
    )


def log_registration_rejected(
    request: Request,
    code: ConnectorRegistrationErrorCode,
    *,
    instance_id: UUID | str | None = None,
    tenant_id: UUID | None = None,
    registration_token_id: UUID | None = None,
    internal_reason: str,
) -> None:
    logger.warning(
        "%s request_id=%s instance_id=%s tenant_id=%s registration_token_id=%s "
        "rejection_code=%s internal_reason=%s",
        _REJECTION_EVENTS[code],
        _request_id(request),
        _value(instance_id),
        _value(tenant_id),
        _value(registration_token_id),
        code.value,
        _safe_reason(internal_reason),
    )


def log_registration_completed(
    request: Request,
    *,
    instance_id: UUID,
    tenant_id: UUID,
    registration_token_id: UUID | None,
) -> None:
    logger.info(
        "connector_registration_completed request_id=%s instance_id=%s tenant_id=%s "
        "registration_token_id=%s rejection_code=-",
        _request_id(request),
        instance_id,
        tenant_id,
        _value(registration_token_id),
    )
