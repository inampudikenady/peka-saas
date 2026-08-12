import logging
import re
from enum import Enum

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import tenant_id_ctx
from app.core.config import settings
from app.core.tenant_registry import tenant_registry
from app.services.tenant_resolver import TenantResolver

logger = logging.getLogger(__name__)

TENANT_PATH_PATTERN = re.compile(r"^/t/([^/]+)(/.*)$")
CONNECTOR_REGISTRATION_PATH = f"{settings.api_prefix}/connectors/register"
CONNECTOR_API_PATH_PATTERN = re.compile(
    rf"^{re.escape(settings.api_prefix)}/connectors(?:/|$)"
)

TENANT_NEUTRAL_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    f"{settings.api_prefix}/openapi.json",
    f"{settings.api_prefix}/platform",
)


class RequestTenancy(str, Enum):
    TENANT_HOST = "tenant_host"
    TENANT_NEUTRAL = "tenant_neutral"
    CONNECTOR_REGISTRATION = "connector_registration"
    CONNECTOR_AUTHENTICATED = "connector_authenticated"


def _matches_path_prefix(path: str, prefix: str) -> bool:
    """Match an exact route or a child route, never a lookalike prefix."""
    return path == prefix or path.startswith(f"{prefix}/")


def classify_request_tenancy(path: str) -> RequestTenancy:
    """Classify how a request obtains tenancy before host resolution runs."""
    if path == CONNECTOR_REGISTRATION_PATH:
        return RequestTenancy.CONNECTOR_REGISTRATION
    if CONNECTOR_API_PATH_PATTERN.match(path) is not None:
        return RequestTenancy.CONNECTOR_AUTHENTICATED
    if any(
        _matches_path_prefix(path, prefix) for prefix in TENANT_NEUTRAL_PATH_PREFIXES
    ):
        return RequestTenancy.TENANT_NEUTRAL
    return RequestTenancy.TENANT_HOST


class TenantContextMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        registry=tenant_registry,
        tenant_url_mode: str | None = None,
    ) -> None:
        super().__init__(app)
        self.resolver = TenantResolver(registry)
        self.tenant_url_mode = tenant_url_mode or settings.tenant_url_mode

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        tenancy = classify_request_tenancy(path)

        if tenancy is not RequestTenancy.TENANT_HOST:
            request.state.request_tenancy = tenancy
            return await call_next(request)

        host = request.headers.get("host", "")
        tenant_context = None
        resolution_source = f"host '{host}'"

        if self.tenant_url_mode == "path":
            path_match = TENANT_PATH_PATTERN.match(path)
            if path_match is not None:
                tenant_slug, stripped_path = path_match.groups()
                tenant_context = self.resolver.resolve_from_slug(tenant_slug)
                resolution_source = f"path slug '{tenant_slug}'"

                if tenant_context is not None:
                    request.scope["path"] = stripped_path
                    request.scope["raw_path"] = stripped_path.encode("utf-8")
        else:
            tenant_context = self.resolver.resolve_from_host(host)

        token = None

        if tenant_context is not None:
            request.state.tenant_context = tenant_context
            request.state.tenant_id = tenant_context.tenant_id
            token = tenant_id_ctx.set(str(tenant_context.tenant_id))

            logger.info(
                "Resolved tenant '%s' from %s",
                tenant_context.slug,
                resolution_source,
            )
        else:
            logger.warning("No tenant found for %s", resolution_source)

        try:
            return await call_next(request)
        finally:
            if token is not None:
                tenant_id_ctx.reset(token)
