from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantDefinition:
    tenant_id: UUID
    slug: str
    hostname: str
    enabled: bool
    display_name: str | None = None
