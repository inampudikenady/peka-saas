from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant, TenantStatus
from app.repositories.base import BaseRepository


class TenantRepository(BaseRepository[Tenant]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, Tenant)

    def get_by_slug(self, slug: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.slug == slug)
        return self.db.scalar(stmt)

    def get_by_subdomain(self, subdomain: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.subdomain == subdomain)
        return self.db.scalar(stmt)

    def get_by_primary_domain(self, domain: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.primary_domain == domain)
        return self.db.scalar(stmt)

    def list_active(self) -> list[Tenant]:
        stmt = (
            select(Tenant)
            .where(Tenant.status == TenantStatus.ACTIVE)
            .order_by(Tenant.name)
        )
        return list(self.db.scalars(stmt).all())

    def list_all(self) -> list[Tenant]:
        stmt = select(Tenant).order_by(Tenant.name)
        return list(self.db.scalars(stmt).all())

    def exists_by_slug(self, slug: str) -> bool:
        return self.get_by_slug(slug) is not None

    def exists_by_domain(self, domain: str) -> bool:
        return self.get_by_primary_domain(domain) is not None
