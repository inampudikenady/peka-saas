from app.core.tenant_context import TenantContext
from app.core.tenant_registry import TenantRegistry


class TenantResolver:
    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry

    def resolve_from_host(self, host: str) -> TenantContext | None:
        hostname = host.split(":", 1)[0].lower()
        definition = self.registry.get(hostname)

        if definition is None or not definition.enabled:
            return None

        return TenantContext(
            tenant_id=definition.tenant_id,
            slug=definition.slug,
            hostname=hostname,
            definition=definition,
        )
