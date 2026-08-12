"""Short-lived outbound connector RPC orchestration for Assistant tools."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.connector import (
    ConnectorCapability,
    ManagedConnector,
    ManagedConnectorStatus,
    OperationalToolRequest,
)
from app.schemas.operational_tools import (
    ALLOWED_OPERATIONAL_TOOLS,
    OperationalToolRequestView,
    OperationalToolResultSubmission,
)


class OperationalToolUnavailable(RuntimeError):
    pass


class OperationalToolConflict(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class OperationalToolService:
    request_ttl = timedelta(seconds=30)
    claim_ttl = timedelta(seconds=15)
    maximum_attempts = 3

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        tenant_id: UUID,
        user_id: UUID,
        tool_name: str,
        arguments: dict,
    ) -> OperationalToolRequest:
        if tool_name not in ALLOWED_OPERATIONAL_TOOLS:
            raise ValueError("Unsupported operational tool")
        now = datetime.now(UTC)
        required_capability = (
            "local_knowledge" if tool_name == "knowledge_search" else "operational_tools"
        )
        connected = {
            ManagedConnectorStatus.CONNECTED,
            ManagedConnectorStatus.IN_SYNC,
            ManagedConnectorStatus.DEGRADED,
        }
        connectors = list(
            self.db.scalars(
                select(ManagedConnector)
                .where(
                    ManagedConnector.tenant_id == tenant_id,
                    ManagedConnector.retired_at.is_(None),
                    ManagedConnector.status.in_(connected),
                    ManagedConnector.id.in_(
                        select(ConnectorCapability.connector_id).where(
                            ConnectorCapability.tenant_id == tenant_id,
                            ConnectorCapability.name == required_capability,
                        )
                    ),
                )
                .order_by(
                    ManagedConnector.last_seen_at.desc().nullslast(),
                    ManagedConnector.registered_at.desc(),
                )
            ).all()
        )
        connector = next(
            (
                item
                for item in connectors
                if item.last_seen_at is not None
                and now - _utc(item.last_seen_at)
                <= timedelta(seconds=max(90, item.heartbeat_interval_seconds * 2))
            ),
            None,
        )
        if connector is None:
            raise OperationalToolUnavailable(
                "No active connector is currently available for this tenant."
            )
        request = OperationalToolRequest(
            tenant_id=tenant_id,
            connector_id=connector.id,
            created_by_user_id=user_id,
            tool_name=tool_name,
            arguments=arguments,
            status="pending",
            expires_at=now + self.request_ttl,
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def claim(self, connector: ManagedConnector) -> OperationalToolRequestView | None:
        now = datetime.now(UTC)
        candidates = list(
            self.db.scalars(
                select(OperationalToolRequest)
                .where(
                    OperationalToolRequest.connector_id == connector.id,
                    OperationalToolRequest.tenant_id == connector.tenant_id,
                    OperationalToolRequest.expires_at > now,
                    OperationalToolRequest.attempt_count < self.maximum_attempts,
                    or_(
                        OperationalToolRequest.status == "pending",
                        (
                            (OperationalToolRequest.status == "claimed")
                            & (OperationalToolRequest.claim_expires_at <= now)
                        ),
                    ),
                )
                .order_by(OperationalToolRequest.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).all()
        )
        request = candidates[0] if candidates else None
        if request is None:
            self._expire_old(now)
            self.db.commit()
            return None
        token = secrets.token_urlsafe(32)
        request.status = "claimed"
        request.claimed_at = now
        request.claim_expires_at = now + self.claim_ttl
        request.claim_token_hash = hashlib.sha256(token.encode()).hexdigest()
        request.attempt_count += 1
        self.db.commit()
        return OperationalToolRequestView(
            id=request.id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            expires_at=request.expires_at,
            claim_token=token,
        )

    def submit(
        self,
        connector: ManagedConnector,
        request_id: UUID,
        submission: OperationalToolResultSubmission,
    ) -> OperationalToolRequest:
        now = datetime.now(UTC)
        request = self.db.scalar(
            select(OperationalToolRequest)
            .where(
                OperationalToolRequest.id == request_id,
                OperationalToolRequest.connector_id == connector.id,
                OperationalToolRequest.tenant_id == connector.tenant_id,
            )
            .with_for_update()
        )
        if request is None:
            raise OperationalToolConflict("Operational tool request was not found.")
        supplied_hash = hashlib.sha256(submission.claim_token.encode()).hexdigest()
        if (
            request.status != "claimed"
            or request.claim_token_hash is None
            or not secrets.compare_digest(supplied_hash, request.claim_token_hash)
            or request.claim_expires_at is None
            or _utc(request.claim_expires_at) <= now
            or _utc(request.expires_at) <= now
        ):
            raise OperationalToolConflict(
                "Operational tool claim is expired or has already been consumed."
            )
        if (
            submission.result is not None
            and len(json.dumps(submission.result, separators=(",", ":"))) > 100_000
        ):
            raise ValueError("Operational tool result is too large.")
        request.status = submission.status
        request.completed_at = now
        request.result = submission.result if submission.status == "completed" else None
        request.error_code = (
            submission.error_code if submission.status == "failed" else None
        )
        request.error_message = (
            submission.error_message if submission.status == "failed" else None
        )
        request.claim_token_hash = None
        request.claim_expires_at = None
        self.db.commit()
        return request

    def result(self, tenant_id: UUID, request_id: UUID) -> OperationalToolRequest:
        self.db.expire_all()
        request = self.db.scalar(
            select(OperationalToolRequest).where(
                OperationalToolRequest.id == request_id,
                OperationalToolRequest.tenant_id == tenant_id,
            )
        )
        if request is None:
            raise OperationalToolUnavailable("Operational tool request was not found.")
        now = datetime.now(UTC)
        if (
            request.status not in {"completed", "failed"}
            and _utc(request.expires_at) <= now
        ):
            request.status = "expired"
            self.db.commit()
        return request

    def clear_ephemeral_payload(self, tenant_id: UUID, request_id: UUID) -> None:
        """Remove raw retrieval context after its authorized consumer has copied it."""
        request = self.db.scalar(
            select(OperationalToolRequest).where(
                OperationalToolRequest.id == request_id,
                OperationalToolRequest.tenant_id == tenant_id,
            )
        )
        if request is None:
            return
        request.result = None
        request.arguments = {}
        self.db.commit()

    def _expire_old(self, now: datetime) -> None:
        for request in self.db.scalars(
            select(OperationalToolRequest).where(
                OperationalToolRequest.status.in_(("pending", "claimed")),
                OperationalToolRequest.expires_at <= now,
            )
        ):
            request.status = "expired"
            request.claim_token_hash = None
            request.claim_expires_at = None
