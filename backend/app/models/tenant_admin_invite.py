from datetime import datetime
from uuid import UUID

import enum

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class TenantInvitePurpose(str, enum.Enum):
    BOOTSTRAP = "bootstrap"
    USER_SETUP = "user_setup"
    PASSWORD_RESET = "password_reset"


class TenantAdminInvite(Entity):
    __tablename__ = "tenant_admin_invites"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by_platform_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    purpose: Mapped[TenantInvitePurpose] = mapped_column(
        Enum(TenantInvitePurpose, name="tenant_invite_purpose"),
        default=TenantInvitePurpose.BOOTSTRAP,
        nullable=False,
    )
