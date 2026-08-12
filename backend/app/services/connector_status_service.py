from datetime import UTC, datetime

from app.models.connector import ManagedConnector, ManagedConnectorStatus


class ConnectorStatusService:
    """Derives SaaS authority status; connector-reported status is never authoritative."""

    authentication_failure_threshold = 3

    def derive(
        self, connector: ManagedConnector, now: datetime | None = None
    ) -> ManagedConnectorStatus:
        now = now or datetime.now(UTC)
        if connector.retired_at is not None:
            return ManagedConnectorStatus.RETIRED
        if (
            connector.authentication_failure_count
            >= self.authentication_failure_threshold
        ):
            return ManagedConnectorStatus.AUTHENTICATION_FAILED
        if connector.last_heartbeat_at is None:
            return ManagedConnectorStatus.DISCONNECTED

        last_heartbeat = connector.last_heartbeat_at
        if last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=UTC)
        elapsed = max(0.0, (now - last_heartbeat).total_seconds())
        interval = connector.heartbeat_interval_seconds
        if elapsed >= 3 * interval:
            return ManagedConnectorStatus.DISCONNECTED
        if elapsed > 1.5 * interval:
            return ManagedConnectorStatus.OUT_OF_SYNC
        if connector.source_unhealthy > 0:
            return ManagedConnectorStatus.DEGRADED
        return ManagedConnectorStatus.CONNECTED

    def recalculate(
        self, connector: ManagedConnector, now: datetime | None = None
    ) -> tuple[ManagedConnectorStatus, ManagedConnectorStatus]:
        previous = connector.status
        current = self.derive(connector, now)
        connector.status = current
        if connector.last_heartbeat_at is None:
            connector.consecutive_missed_heartbeats = 0
        elif current == ManagedConnectorStatus.OUT_OF_SYNC:
            connector.consecutive_missed_heartbeats = 2
        elif current == ManagedConnectorStatus.DISCONNECTED:
            connector.consecutive_missed_heartbeats = 3
        elif current not in (
            ManagedConnectorStatus.AUTHENTICATION_FAILED,
            ManagedConnectorStatus.RETIRED,
        ):
            connector.consecutive_missed_heartbeats = 0
        return previous, current
