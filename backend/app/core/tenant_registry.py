from threading import RLock

from app.core.tenant_definition import TenantDefinition


class TenantRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._by_host: dict[str, TenantDefinition] = {}

    def get(self, host: str) -> TenantDefinition | None:
        with self._lock:
            return self._by_host.get(host.lower())

    def add(self, definition: TenantDefinition) -> None:
        with self._lock:
            self._by_host[definition.hostname.lower()] = definition

    def remove(self, host: str) -> None:
        with self._lock:
            self._by_host.pop(host.lower(), None)

    def clear(self) -> None:
        with self._lock:
            self._by_host.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._by_host)


tenant_registry = TenantRegistry()
