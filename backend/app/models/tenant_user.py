import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class TenantUserAuthSource(str, enum.Enum):
    LOCAL = "local"
    SSO = "sso"


class TenantUserRole(str, enum.Enum):
    TENANT_ADMIN = "tenant_admin"
    TENANT_USER = "tenant_user"


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

    role: Mapped[TenantUserRole] = mapped_column(
        Enum(TenantUserRole, name="tenant_user_role"),
        default=TenantUserRole.TENANT_USER,
        nullable=False,
    )

    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TenantPasswordResetToken(Entity):
    __tablename__ = "tenant_password_reset_tokens"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_platform_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DevelopmentEmail(Entity):
    __tablename__ = "development_emails"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    action_url: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_state: Mapped[str] = mapped_column(
        String(50), nullable=False, default="captured"
    )
