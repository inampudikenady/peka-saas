from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_oidc_auth_session import TenantOIDCAuthSession
from app.repositories.base import BaseRepository


class TenantOIDCAuthSessionRepository(
    BaseRepository[TenantOIDCAuthSession]
):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TenantOIDCAuthSession)

    def get_by_state_hash(
        self,
        state_hash: str,
    ) -> TenantOIDCAuthSession | None:
        stmt = select(TenantOIDCAuthSession).where(
            TenantOIDCAuthSession.state_hash == state_hash
        )
        return self.db.scalar(stmt)
