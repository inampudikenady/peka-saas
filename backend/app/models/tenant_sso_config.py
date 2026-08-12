import enum
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Entity


class SSOProvider(str, enum.Enum):
    MICROSOFT_ENTRA = "microsoft_entra"
    GENERIC_OIDC = "generic_oidc"


class TenantSSOConfig(Entity):
    __tablename__ = "tenant_sso_configs"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[SSOProvider] = mapped_column(
        Enum(SSOProvider, name="sso_provider"),
        nullable=False,
    )

    entra_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issuer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_encrypted: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )

    authorization_endpoint: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    token_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)

    redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)

    scopes: Mapped[str] = mapped_column(
        String(500),
        default="openid profile email",
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_sso_config_tenant_id"),
    )

    @property
    def client_secret_configured(self) -> bool:
        return bool(self.client_secret_encrypted)
