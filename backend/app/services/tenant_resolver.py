from app.core.tenant_context import TenantContext
from app.core.tenant_definition import TenantDefinition
from app.core.tenant_registry import TenantRegistry


class TenantResolver:
    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry

    def resolve_from_host(self, host: str) -> TenantContext | None:
        hostname = host.split(":", 1)[0].lower()
        definition = self.registry.get(hostname)

        return self._build_context(definition, hostname)

    def resolve_from_slug(self, slug: str) -> TenantContext | None:
        definition = self.registry.get_by_slug(slug)

        return self._build_context(
            definition, definition.hostname if definition else ""
        )

    @staticmethod
    def _build_context(
        definition: TenantDefinition | None,
        hostname: str,
    ) -> TenantContext | None:
        if definition is None or not definition.enabled:
            return None

        return TenantContext(
            tenant_id=definition.tenant_id,
            slug=definition.slug,
            hostname=hostname,
            definition=definition,
        )
