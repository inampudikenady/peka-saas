from dataclasses import dataclass
from uuid import UUID

from app.core.tenant_definition import TenantDefinition


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    slug: str
    hostname: str
    definition: TenantDefinition
