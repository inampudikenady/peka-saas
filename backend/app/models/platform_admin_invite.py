import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class PlatformAdminInvitePurpose(str, enum.Enum):
    SETUP = "setup"
    PASSWORD_RESET = "password_reset"


class PlatformAdminInvite(Entity):
    __tablename__ = "platform_admin_invites"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_admin_users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    purpose: Mapped[PlatformAdminInvitePurpose] = mapped_column(
        Enum(PlatformAdminInvitePurpose, name="platform_admin_invite_purpose")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_platform_admin_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_admin_users.id", ondelete="CASCADE"), index=True
    )
