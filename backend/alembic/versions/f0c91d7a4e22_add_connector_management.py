"""Add managed connector lifecycle tables.

Revision ID: f0c91d7a4e22
Revises: eaf812c6b432
"""

from alembic import op
import sqlalchemy as sa


revision = "f0c91d7a4e22"
down_revision = "eaf812c6b432"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    connector_status = sa.Enum("CONNECTED", "IN_SYNC", "DEGRADED", "OUT_OF_SYNC", "DISCONNECTED", "AUTHENTICATION_FAILED", "RETIRED", name="managed_connector_status")
    event_type = sa.Enum(
        "REGISTRATION_TOKEN_GENERATED", "REGISTRATION_TOKEN_REVOKED", "REGISTRATION_TOKEN_USED",
        "REGISTRATION_TOKEN_EXPIRED", "REGISTRATION_TOKEN_FAILED", "REGISTERED", "HEARTBEAT_RECEIVED",
        "SOURCE_HEALTH_CHANGED", "STATUS_CHANGED", "AUTHENTICATION_FAILURE", "RETIRED",
        name="connector_event_type",
    )

    op.create_table(
        "connector_registration_tokens",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intended_connector_name", sa.String(255), nullable=True),
        sa.Column("expiration_event_recorded_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connector_registration_tokens_token_hash", "connector_registration_tokens", ["token_hash"], unique=True)
    op.create_index("ix_connector_registration_tokens_tenant_id", "connector_registration_tokens", ["tenant_id"])
    op.create_index("ix_connector_registration_tokens_expires_at", "connector_registration_tokens", ["expires_at"])
    op.create_index("ix_connector_registration_tokens_created_by_user_id", "connector_registration_tokens", ["created_by_user_id"])
    op.create_index("ix_connector_registration_tokens_tenant_created", "connector_registration_tokens", ["tenant_id", "created_at"])

    op.create_table(
        "managed_connectors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("environment", sa.String(100), nullable=False),
        sa.Column("status", connector_status, nullable=False),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_interval_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column("source_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_healthy", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_unhealthy", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_disabled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_missed_heartbeats", sa.Integer(), server_default="0", nullable=False),
        sa.Column("authentication_failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("heartbeat_interval_seconds > 0", name="ck_managed_connectors_heartbeat_interval"),
        sa.CheckConstraint("source_total >= 0 AND source_healthy >= 0 AND source_unhealthy >= 0 AND source_disabled >= 0", name="ck_managed_connectors_source_counts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_managed_connectors_tenant_id", "managed_connectors", ["tenant_id"])
    op.create_index("ix_managed_connectors_tenant_status", "managed_connectors", ["tenant_id", "status"])
    op.create_index("uq_managed_connectors_active_tenant_instance", "managed_connectors", ["tenant_id", "instance_id"], unique=True, postgresql_where=sa.text("retired_at IS NULL"))

    op.create_table(
        "connector_heartbeats",
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("reported_status", sa.String(50), nullable=False),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False),
        sa.Column("source_total", sa.Integer(), nullable=False),
        sa.Column("source_healthy", sa.Integer(), nullable=False),
        sa.Column("source_unhealthy", sa.Integer(), nullable=False),
        sa.Column("source_disabled", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connector_heartbeats_connector_id", "connector_heartbeats", ["connector_id"])
    op.create_index("ix_connector_heartbeats_tenant_id", "connector_heartbeats", ["tenant_id"])
    op.create_index("ix_connector_heartbeats_connector_received", "connector_heartbeats", ["connector_id", "received_at"])

    op.create_table(
        "connector_capabilities",
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connector_id", "name", name="uq_connector_capabilities_connector_name"),
    )
    op.create_index("ix_connector_capabilities_connector_id", "connector_capabilities", ["connector_id"])
    op.create_index("ix_connector_capabilities_tenant_id", "connector_capabilities", ["tenant_id"])

    op.create_table(
        "connector_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=True),
        sa.Column("registration_token_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["managed_connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registration_token_id"], ["connector_registration_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connector_events_tenant_id", "connector_events", ["tenant_id"])
    op.create_index("ix_connector_events_connector_id", "connector_events", ["connector_id"])
    op.create_index("ix_connector_events_connector_occurred", "connector_events", ["connector_id", "occurred_at"])
    op.create_index("ix_connector_events_tenant_occurred", "connector_events", ["tenant_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("connector_events")
    op.drop_table("connector_capabilities")
    op.drop_table("connector_heartbeats")
    op.drop_table("managed_connectors")
    op.drop_table("connector_registration_tokens")
    sa.Enum(name="connector_event_type").drop(op.get_bind())
    sa.Enum(name="managed_connector_status").drop(op.get_bind())
