from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class TenantAuditEvent(Entity):
    """Durable platform audit event retained even after tenant deletion."""

    __tablename__ = "tenant_audit_events"
    __table_args__ = (
        Index("ix_tenant_audit_slug_created", "tenant_slug", "created_at"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    tenant_slug: Mapped[str] = mapped_column(String(100), index=True)
    tenant_display_name: Mapped[str] = mapped_column(String(255))
    actor_platform_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_username: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80), index=True)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
