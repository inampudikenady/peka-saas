import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class TenantUserAuthSource(str, enum.Enum):
    LOCAL = "local"
    SSO = "sso"


class TenantUser(Entity):
    __tablename__ = "tenant_users"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    auth_source: Mapped[TenantUserAuthSource] = mapped_column(
        Enum(TenantUserAuthSource, name="tenant_user_auth_source"),
        nullable=False,
    )

    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    external_subject: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
