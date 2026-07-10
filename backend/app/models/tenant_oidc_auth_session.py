from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class TenantOIDCAuthSession(Entity):
    __tablename__ = "tenant_oidc_auth_sessions"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    state_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )

    nonce: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    code_verifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    redirect_uri: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
