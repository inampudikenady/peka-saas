from threading import RLock

from app.core.tenant_definition import TenantDefinition


class TenantRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._by_host: dict[str, TenantDefinition] = {}
        self._by_slug: dict[str, TenantDefinition] = {}

    def get(self, host: str) -> TenantDefinition | None:
        with self._lock:
            return self._by_host.get(host.lower())

    def get_by_slug(self, slug: str) -> TenantDefinition | None:
        with self._lock:
            return self._by_slug.get(slug.lower())

    def add(self, definition: TenantDefinition) -> None:
        with self._lock:
            existing = self._by_slug.get(definition.slug.lower())
            if existing is not None and existing.hostname:
                self._by_host.pop(existing.hostname.lower(), None)

            if definition.hostname:
                self._by_host[definition.hostname.lower()] = definition
            self._by_slug[definition.slug.lower()] = definition

    def remove(self, host: str) -> None:
        with self._lock:
            definition = self._by_host.pop(host.lower(), None)
            if definition is not None:
                self._by_slug.pop(definition.slug.lower(), None)

    def clear(self) -> None:
        with self._lock:
            self._by_host.clear()
            self._by_slug.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._by_slug)


tenant_registry = TenantRegistry()
