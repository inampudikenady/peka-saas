from datetime import UTC, datetime, timedelta
from typing import Literal, NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.core.connector_security import (
    generate_connector_secret,
    generate_registration_token,
    hash_connector_secret,
    hash_registration_token,
    verify_connector_secret,
)
from app.models.connector import (
    ConnectorEvent,
    ConnectorEventType,
    ConnectorHeartbeat,
    ConnectorRegistrationToken,
    ManagedConnector,
    ManagedConnectorStatus,
)
from app.models.tenant import TenantStatus
from app.models.tenant_user import TenantUser
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.tenant_repository import TenantRepository
from app.schemas.connector_api import (
    ConnectorDetailResponse,
    ConnectorEventResponse,
    ConnectorHeartbeatHistoryResponse,
    ConnectorHeartbeatRequest,
    ConnectorHeartbeatResponse,
    ConnectorRegistrationRequest,
    ConnectorRegistrationErrorCode,
    ConnectorRegistrationResponse,
    ConnectorSummaryResponse,
    RegistrationTokenCreatedResponse,
    RegistrationTokenResponse,
)
from app.services.connector_status_service import ConnectorStatusService


class ConnectorServiceError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConnectorRegistrationError(ConnectorServiceError):
    def __init__(
        self,
        code: ConnectorRegistrationErrorCode,
        message: str,
        status_code: int,
        *,
        tenant_id: UUID | None = None,
        registration_token_id: UUID | None = None,
        internal_reason: str,
    ) -> None:
        super().__init__(message, status_code)
        self.code = code
        self.tenant_id = tenant_id
        self.registration_token_id = registration_token_id
        self.internal_reason = internal_reason


class ConnectorService:
    token_lifetime = timedelta(minutes=30)
    heartbeat_interval_seconds = 300
    heartbeat_retention = timedelta(days=30)
    _dummy_secret_hash: str | None = None

    def __init__(
        self,
        repository: ConnectorRepository,
        tenant_repository: TenantRepository,
        *,
        connector_limit: int | None = None,
    ) -> None:
        self.repository = repository
        self.tenant_repository = tenant_repository
        self.connector_limit = connector_limit
        self.status_service = ConnectorStatusService()

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        """Normalize drivers (notably SQLite in tests) that drop timezone metadata."""
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    def _event(
        self,
        tenant_id: UUID,
        event_type: ConnectorEventType,
        *,
        connector_id: UUID | None = None,
        token_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        detail: str | None = None,
        now: datetime | None = None,
    ) -> ConnectorEvent:
        return self.repository.add(
            ConnectorEvent(
                tenant_id=tenant_id,
                connector_id=connector_id,
                registration_token_id=token_id,
                event_type=event_type,
                actor_user_id=actor_user_id,
                detail=detail,
                occurred_at=now or self.now(),
            )
        )

    @staticmethod
    def _token_status(
        token: ConnectorRegistrationToken, now: datetime
    ) -> Literal["active", "used", "expired", "revoked"]:
        if token.used_at is not None:
            return "used"
        if token.revoked_at is not None:
            return "revoked"
        if ConnectorService._utc(token.expires_at) <= now:
            return "expired"
        return "active"

    def _token_response(
        self, token: ConnectorRegistrationToken, now: datetime, raw: str | None = None
    ):
        status = self._token_status(token, now)
        if raw is not None:
            return RegistrationTokenCreatedResponse(
                id=token.id,
                tenant_id=token.tenant_id,
                expires_at=token.expires_at,
                used_at=token.used_at,
                created_by_user_id=token.created_by_user_id,
                created_at=token.created_at,
                revoked_at=token.revoked_at,
                intended_connector_name=token.intended_connector_name,
                status=status,
                registration_token=raw,
            )
        return RegistrationTokenResponse(
            id=token.id,
            tenant_id=token.tenant_id,
            expires_at=token.expires_at,
            used_at=token.used_at,
            created_by_user_id=token.created_by_user_id,
            created_at=token.created_at,
            revoked_at=token.revoked_at,
            intended_connector_name=token.intended_connector_name,
            status=status,
        )

    def create_registration_token(
        self, tenant_id: UUID, actor: TenantUser, intended_name: str | None
    ) -> RegistrationTokenCreatedResponse:
        now = self.now()
        raw = generate_registration_token()
        token = ConnectorRegistrationToken(
            tenant_id=tenant_id,
            token_hash=hash_registration_token(raw),
            expires_at=now + self.token_lifetime,
            created_by_user_id=actor.id,
            intended_connector_name=intended_name,
        )
        try:
            self.repository.add(token)
            self._event(
                tenant_id,
                ConnectorEventType.REGISTRATION_TOKEN_GENERATED,
                token_id=token.id,
                actor_user_id=actor.id,
                detail="Single-use registration token generated.",
                now=now,
            )
            self.repository.commit()
            return self._token_response(token, now, raw)
        except SQLAlchemyError:
            self.repository.rollback()
            raise

    def list_registration_tokens(
        self, tenant_id: UUID, *, include_inactive: bool = False
    ) -> list[RegistrationTokenResponse]:
        now = self.now()
        tokens = self.repository.list_registration_tokens(
            tenant_id,
            include_inactive=include_inactive,
            now=now,
        )
        changed = False
        for token in tokens:
            if (
                token.used_at is None
                and token.revoked_at is None
                and self._utc(token.expires_at) <= now
                and token.expiration_event_recorded_at is None
            ):
                token.expiration_event_recorded_at = now
                self._event(
                    tenant_id,
                    ConnectorEventType.REGISTRATION_TOKEN_EXPIRED,
                    token_id=token.id,
                    detail="Registration token expired.",
                    now=now,
                )
                changed = True
        if changed:
            self.repository.commit()
        return [self._token_response(token, now) for token in tokens]

    def revoke_registration_token(
        self, tenant_id: UUID, token_id: UUID, actor: TenantUser
    ) -> RegistrationTokenResponse:
        token = self.repository.get_registration_token(tenant_id, token_id)
        if token is None:
            raise ConnectorServiceError("Registration token not found.", 404)
        now = self.now()
        if token.used_at is not None:
            raise ConnectorServiceError(
                "Used registration tokens cannot be revoked.", 409
            )
        if token.revoked_at is None:
            token.revoked_at = now
            self._event(
                tenant_id,
                ConnectorEventType.REGISTRATION_TOKEN_REVOKED,
                token_id=token.id,
                actor_user_id=actor.id,
                detail="Registration token revoked.",
                now=now,
            )
            self.repository.commit()
        return self._token_response(token, now)

    def _failed_token_use(
        self,
        token: ConnectorRegistrationToken,
        detail: str,
        error_code: ConnectorRegistrationErrorCode,
        status_code: int,
        now: datetime,
        *,
        internal_reason: str | None = None,
    ) -> NoReturn:
        tenant_id = token.tenant_id
        token_id = token.id
        self._event(
            tenant_id,
            ConnectorEventType.REGISTRATION_TOKEN_FAILED,
            token_id=token_id,
            detail=detail,
            now=now,
        )
        self.repository.commit()
        raise ConnectorRegistrationError(
            error_code,
            detail,
            status_code,
            tenant_id=tenant_id,
            registration_token_id=token_id,
            internal_reason=internal_reason or error_code.value.lower(),
        )

    def register(
        self, payload: ConnectorRegistrationRequest
    ) -> ConnectorRegistrationResponse:
        now = self.now()
        token = self.repository.get_registration_token_for_update(
            hash_registration_token(payload.registration_token)
        )
        if token is None:
            raise ConnectorRegistrationError(
                ConnectorRegistrationErrorCode.TOKEN_NOT_FOUND,
                "The registration token is invalid or not permitted.",
                401,
                internal_reason="token_not_found",
            )
        token_tenant_id = token.tenant_id
        token_id = token.id
        if token.used_at is not None:
            self._failed_token_use(
                token,
                "The registration token has already been used.",
                ConnectorRegistrationErrorCode.TOKEN_USED,
                410,
                now,
            )
        if token.revoked_at is not None:
            self._failed_token_use(
                token,
                "The registration token has been revoked.",
                ConnectorRegistrationErrorCode.TOKEN_REVOKED,
                410,
                now,
            )
        if self._utc(token.expires_at) <= now:
            if token.expiration_event_recorded_at is None:
                token.expiration_event_recorded_at = now
                self._event(
                    token.tenant_id,
                    ConnectorEventType.REGISTRATION_TOKEN_EXPIRED,
                    token_id=token.id,
                    detail="Registration token expired.",
                    now=now,
                )
            self._failed_token_use(
                token,
                "The registration token has expired.",
                ConnectorRegistrationErrorCode.TOKEN_EXPIRED,
                410,
                now,
            )
        tenant = self.tenant_repository.get_by_id(token.tenant_id)
        if tenant is not None and tenant.id != token.tenant_id:
            self._failed_token_use(
                token,
                "The registration token is not valid for this tenant.",
                ConnectorRegistrationErrorCode.TENANT_MISMATCH,
                403,
                now,
            )
        if tenant is None:
            self._failed_token_use(
                token,
                "Connector registration is not permitted.",
                ConnectorRegistrationErrorCode.REGISTRATION_NOT_PERMITTED,
                403,
                now,
                internal_reason="tenant_not_found",
            )
        if tenant.status != TenantStatus.ACTIVE:
            self._failed_token_use(
                token,
                "Connector registration is not permitted for an inactive tenant.",
                ConnectorRegistrationErrorCode.TENANT_INACTIVE,
                403,
                now,
                internal_reason=f"tenant_{tenant.status.value}",
            )
        if (
            self.repository.get_active_by_instance(token.tenant_id, payload.instance_id)
            is not None
        ):
            self._failed_token_use(
                token,
                "This connector appliance is already registered.",
                ConnectorRegistrationErrorCode.INSTANCE_ALREADY_REGISTERED,
                409,
                now,
            )
        if (
            self.connector_limit is not None
            and self.repository.count_active_for_tenant(token.tenant_id)
            >= self.connector_limit
        ):
            self._failed_token_use(
                token,
                "The tenant connector limit has been reached.",
                ConnectorRegistrationErrorCode.CONNECTOR_LIMIT_REACHED,
                409,
                now,
                internal_reason="connector_limit_reached",
            )

        raw_secret = generate_connector_secret()
        connector = ManagedConnector(
            tenant_id=token.tenant_id,
            name=payload.connector_name,
            instance_id=payload.instance_id,
            version=payload.connector_version,
            environment=payload.environment,
            status=ManagedConnectorStatus.DISCONNECTED,
            secret_hash=hash_connector_secret(raw_secret),
            registered_at=now,
            last_seen_at=now,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
        )
        try:
            self.repository.add(connector)
            self.repository.replace_capabilities(
                connector, list(payload.capabilities), now
            )
            token.used_at = now
            self._event(
                token.tenant_id,
                ConnectorEventType.REGISTRATION_TOKEN_USED,
                connector_id=connector.id,
                token_id=token.id,
                detail="Registration token consumed.",
                now=now,
            )
            self._event(
                token.tenant_id,
                ConnectorEventType.REGISTERED,
                connector_id=connector.id,
                token_id=token.id,
                detail="Connector registered.",
                now=now,
            )
            self.repository.commit()
        except IntegrityError as exc:
            self.repository.rollback()
            if (
                self.repository.get_active_by_instance(
                    token_tenant_id, payload.instance_id
                )
                is not None
            ):
                raise ConnectorRegistrationError(
                    ConnectorRegistrationErrorCode.INSTANCE_ALREADY_REGISTERED,
                    "This connector appliance is already registered.",
                    409,
                    tenant_id=token_tenant_id,
                    registration_token_id=token_id,
                    internal_reason="duplicate_active_instance_integrity_conflict",
                ) from exc
            raise ConnectorRegistrationError(
                ConnectorRegistrationErrorCode.INTERNAL_ERROR,
                "Connector registration failed unexpectedly.",
                500,
                tenant_id=token_tenant_id,
                registration_token_id=token_id,
                internal_reason="database_integrity_error",
            ) from exc
        except SQLAlchemyError as exc:
            self.repository.rollback()
            raise ConnectorRegistrationError(
                ConnectorRegistrationErrorCode.INTERNAL_ERROR,
                "Connector registration failed unexpectedly.",
                500,
                tenant_id=token_tenant_id,
                registration_token_id=token_id,
                internal_reason="database_operation_error",
            ) from exc
        response = ConnectorRegistrationResponse(
            connector_id=connector.id,
            tenant_id=connector.tenant_id,
            connector_secret=raw_secret,
            heartbeat_interval_seconds=connector.heartbeat_interval_seconds,
            registered_at=connector.registered_at,
            tenant_timezone=tenant.timezone,
        )
        response._registration_token_id = token_id
        return response

    def _record_auth_failure(self, connector: ManagedConnector, now: datetime) -> None:
        connector.authentication_failure_count += 1
        connector.last_seen_at = now
        old, new = self.status_service.recalculate(connector, now)
        self._event(
            connector.tenant_id,
            ConnectorEventType.AUTHENTICATION_FAILURE,
            connector_id=connector.id,
            detail="Connector bearer authentication failed.",
            now=now,
        )
        if old != new:
            self._event(
                connector.tenant_id,
                ConnectorEventType.STATUS_CHANGED,
                connector_id=connector.id,
                detail=f"Status changed from {old.value} to {new.value}.",
                now=now,
            )
        self.repository.commit()

    def authenticate(
        self,
        connector_id: UUID,
        header_connector_id: str | None,
        bearer_secret: str | None,
        *,
        retired_status_code: int = 401,
        reject_authentication_failed: bool = False,
    ) -> ManagedConnector:
        """Authenticate an appliance without applying heartbeat side effects."""
        now = self.now()
        connector = self.repository.get_unscoped(connector_id)
        if self._dummy_secret_hash is None:
            self.__class__._dummy_secret_hash = hash_connector_secret(
                "invalid-connector-secret-for-timing-equalization"
            )
        hash_to_check = (
            connector.secret_hash if connector is not None else self._dummy_secret_hash
        )
        authenticated = bearer_secret is not None and verify_connector_secret(
            bearer_secret, hash_to_check or ""
        )
        header_matches = header_connector_id == str(connector_id)
        if connector is None or not authenticated or not header_matches:
            if connector is not None:
                self._record_auth_failure(connector, now)
            raise ConnectorServiceError("Connector authentication failed.", 401)
        if connector.retired_at is not None:
            message = (
                "Connector is retired."
                if retired_status_code != 401
                else "Connector authentication failed."
            )
            raise ConnectorServiceError(message, retired_status_code)
        if (
            reject_authentication_failed
            and connector.status == ManagedConnectorStatus.AUTHENTICATION_FAILED
        ):
            raise ConnectorServiceError(
                "Connector authentication is locked after repeated failures.", 403
            )
        connector.last_seen_at = now
        return connector

    def heartbeat(
        self,
        connector_id: UUID,
        header_connector_id: str | None,
        bearer_secret: str | None,
        payload: ConnectorHeartbeatRequest,
    ) -> ConnectorHeartbeatResponse:
        connector = self.authenticate(connector_id, header_connector_id, bearer_secret)
        return self.record_heartbeat(connector, payload)

    def record_heartbeat(
        self,
        connector: ManagedConnector,
        payload: ConnectorHeartbeatRequest,
    ) -> ConnectorHeartbeatResponse:
        """Persist a heartbeat for a connector authenticated by the API boundary."""
        now = self.now()
        if payload.instance_id != connector.instance_id:
            self.repository.add(
                ConnectorHeartbeat(
                    connector_id=connector.id,
                    tenant_id=connector.tenant_id,
                    received_at=now,
                    reported_at=payload.timestamp,
                    version=payload.connector_version,
                    reported_status=payload.status,
                    uptime_seconds=payload.uptime_seconds,
                    source_total=payload.sources.total,
                    source_healthy=payload.sources.healthy,
                    source_unhealthy=payload.sources.unhealthy,
                    source_disabled=payload.sources.disabled,
                    accepted=False,
                )
            )
            self._event(
                connector.tenant_id,
                ConnectorEventType.AUTHENTICATION_FAILURE,
                connector_id=connector.id,
                detail="Authenticated heartbeat instance ID mismatch.",
                now=now,
            )
            self.repository.commit()
            raise ConnectorServiceError(
                "Heartbeat instance ID does not match registration.", 409
            )

        previous_sources = (
            connector.source_total,
            connector.source_healthy,
            connector.source_unhealthy,
            connector.source_disabled,
        )
        previous_status = connector.status
        if payload.connector_name is not None:
            connector.name = payload.connector_name
        if payload.environment is not None:
            connector.environment = payload.environment
        connector.version = payload.connector_version
        connector.last_heartbeat_at = now
        connector.last_seen_at = now
        connector.source_total = payload.sources.total
        connector.source_healthy = payload.sources.healthy
        connector.source_unhealthy = payload.sources.unhealthy
        connector.source_disabled = payload.sources.disabled
        if payload.local_knowledge_store is not None:
            knowledge = payload.local_knowledge_store
            connector.local_knowledge_store_status = knowledge.status
            connector.knowledge_document_count = knowledge.documents
            connector.knowledge_indexed_chunk_count = knowledge.indexed_chunks
            connector.last_knowledge_index_activity_at = knowledge.last_index_activity
        connector.authentication_failure_count = 0
        connector.consecutive_missed_heartbeats = 0
        self.status_service.recalculate(connector, now)
        self.repository.add(
            ConnectorHeartbeat(
                connector_id=connector.id,
                tenant_id=connector.tenant_id,
                received_at=now,
                reported_at=payload.timestamp,
                version=payload.connector_version,
                reported_status=payload.status,
                uptime_seconds=payload.uptime_seconds,
                source_total=payload.sources.total,
                source_healthy=payload.sources.healthy,
                source_unhealthy=payload.sources.unhealthy,
                source_disabled=payload.sources.disabled,
                local_knowledge_store_status=(
                    payload.local_knowledge_store.status
                    if payload.local_knowledge_store is not None
                    else None
                ),
                knowledge_document_count=(
                    payload.local_knowledge_store.documents
                    if payload.local_knowledge_store is not None
                    else 0
                ),
                knowledge_indexed_chunk_count=(
                    payload.local_knowledge_store.indexed_chunks
                    if payload.local_knowledge_store is not None
                    else 0
                ),
                last_knowledge_index_activity_at=(
                    payload.local_knowledge_store.last_index_activity
                    if payload.local_knowledge_store is not None
                    else None
                ),
                accepted=True,
            )
        )
        self.repository.replace_capabilities(connector, list(payload.capabilities), now)
        self._event(
            connector.tenant_id,
            ConnectorEventType.HEARTBEAT_RECEIVED,
            connector_id=connector.id,
            detail="Heartbeat accepted.",
            now=now,
        )
        current_sources = (
            connector.source_total,
            connector.source_healthy,
            connector.source_unhealthy,
            connector.source_disabled,
        )
        if previous_sources != current_sources:
            self._event(
                connector.tenant_id,
                ConnectorEventType.SOURCE_HEALTH_CHANGED,
                connector_id=connector.id,
                detail="Reported source health summary changed.",
                now=now,
            )
        if previous_status != connector.status:
            self._event(
                connector.tenant_id,
                ConnectorEventType.STATUS_CHANGED,
                connector_id=connector.id,
                detail=f"Status changed from {previous_status.value} to {connector.status.value}.",
                now=now,
            )
        try:
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            raise
        tenant = self.tenant_repository.get_by_id(connector.tenant_id)
        if tenant is None:
            raise ConnectorServiceError("Connector tenant no longer exists.", 409)
        return ConnectorHeartbeatResponse(
            server_time=now,
            next_heartbeat_seconds=connector.heartbeat_interval_seconds,
            tenant_timezone=tenant.timezone,
        )

    def _recalculate_many(
        self, connectors: list[ManagedConnector], now: datetime
    ) -> None:
        changed = False
        for connector in connectors:
            old, new = self.status_service.recalculate(connector, now)
            if old != new:
                self._event(
                    connector.tenant_id,
                    ConnectorEventType.STATUS_CHANGED,
                    connector_id=connector.id,
                    detail=f"Status changed from {old.value} to {new.value}.",
                    now=now,
                )
                changed = True
        if changed:
            self.repository.commit()

    @staticmethod
    def _summary(
        connector: ManagedConnector,
        tenant_name: str | None = None,
        tenant_slug: str | None = None,
        tenant_timezone: str | None = None,
    ) -> ConnectorSummaryResponse:
        return ConnectorSummaryResponse(
            id=connector.id,
            tenant_id=connector.tenant_id,
            tenant_name=tenant_name,
            tenant_slug=tenant_slug,
            tenant_timezone=tenant_timezone,
            name=connector.name,
            instance_id=connector.instance_id,
            version=connector.version,
            environment=connector.environment,
            status=connector.status.value,
            registered_at=connector.registered_at,
            last_heartbeat_at=connector.last_heartbeat_at,
            last_seen_at=connector.last_seen_at,
            heartbeat_interval_seconds=connector.heartbeat_interval_seconds,
            source_total=connector.source_total,
            source_healthy=connector.source_healthy,
            source_unhealthy=connector.source_unhealthy,
            source_disabled=connector.source_disabled,
            local_knowledge_store_status=connector.local_knowledge_store_status,
            knowledge_document_count=connector.knowledge_document_count,
            knowledge_indexed_chunk_count=connector.knowledge_indexed_chunk_count,
            last_knowledge_index_activity_at=connector.last_knowledge_index_activity_at,
            retired_at=connector.retired_at,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )

    def list_tenant_connectors(
        self, tenant_id: UUID, *, include_retired: bool = False
    ) -> list[ConnectorSummaryResponse]:
        connectors = self.repository.list_for_tenant(
            tenant_id, include_retired=include_retired
        )
        self._recalculate_many(connectors, self.now())
        tenant = self.tenant_repository.get_by_id(tenant_id)
        return [
            self._summary(
                connector, tenant_timezone=tenant.timezone if tenant else None
            )
            for connector in connectors
        ]

    def list_platform_connectors(
        self, *, include_retired: bool = False
    ) -> list[ConnectorSummaryResponse]:
        rows = self.repository.list_for_platform(include_retired=include_retired)
        self._recalculate_many([row[0] for row in rows], self.now())
        return [
            self._summary(connector, tenant.display_name, tenant.slug, tenant.timezone)
            for connector, tenant in rows
        ]

    def detail(
        self,
        connector: ManagedConnector,
        tenant_name: str | None = None,
        tenant_slug: str | None = None,
        tenant_timezone: str | None = None,
    ) -> ConnectorDetailResponse:
        self._recalculate_many([connector], self.now())
        summary = self._summary(
            connector, tenant_name, tenant_slug, tenant_timezone
        ).model_dump()
        return ConnectorDetailResponse(
            **summary,
            capabilities=self.repository.list_capabilities(
                connector.tenant_id, connector.id
            ),
            recent_heartbeats=[
                ConnectorHeartbeatHistoryResponse.model_validate(item)
                for item in self.repository.recent_heartbeats(
                    connector.tenant_id, connector.id
                )
            ],
            recent_events=[
                ConnectorEventResponse.model_validate(item)
                for item in self.repository.recent_events(
                    connector.tenant_id, connector.id
                )
            ],
        )

    def get_tenant_detail(
        self, tenant_id: UUID, connector_id: UUID
    ) -> ConnectorDetailResponse:
        connector = self.repository.get(tenant_id, connector_id)
        if connector is None:
            raise ConnectorServiceError("Connector not found.", 404)
        tenant = self.tenant_repository.get_by_id(tenant_id)
        return self.detail(
            connector,
            tenant.display_name if tenant else None,
            tenant.slug if tenant else None,
            tenant.timezone if tenant else None,
        )

    def get_platform_detail(self, connector_id: UUID) -> ConnectorDetailResponse:
        connector = self.repository.get_unscoped(connector_id)
        if connector is None:
            raise ConnectorServiceError("Connector not found.", 404)
        tenant = self.tenant_repository.get_by_id(connector.tenant_id)
        return self.detail(
            connector,
            tenant.display_name if tenant else None,
            tenant.slug if tenant else None,
            tenant.timezone if tenant else None,
        )

    def retire(
        self, tenant_id: UUID, connector_id: UUID, actor: TenantUser
    ) -> ConnectorDetailResponse:
        connector = self.repository.get(tenant_id, connector_id)
        if connector is None:
            raise ConnectorServiceError("Connector not found.", 404)
        if connector.retired_at is None:
            now = self.now()
            connector.retired_at = now
            connector.status = ManagedConnectorStatus.RETIRED
            self._event(
                tenant_id,
                ConnectorEventType.RETIRED,
                connector_id=connector.id,
                actor_user_id=actor.id,
                detail="Connector retired by tenant administrator.",
                now=now,
            )
            self.repository.commit()
        return self.detail(connector)

    def maintenance(self) -> tuple[int, int]:
        now = self.now()
        connectors = self.repository.list_all()
        self._recalculate_many(connectors, now)
        expired_tokens = self.repository.list_unrecorded_expired_tokens(now)
        for token in expired_tokens:
            token.expiration_event_recorded_at = now
            self._event(
                token.tenant_id,
                ConnectorEventType.REGISTRATION_TOKEN_EXPIRED,
                token_id=token.id,
                detail="Registration token expired.",
                now=now,
            )
        deleted = self.repository.delete_heartbeats_before(
            now - self.heartbeat_retention
        )
        if deleted or expired_tokens:
            self.repository.commit()
        return len(connectors), deleted
