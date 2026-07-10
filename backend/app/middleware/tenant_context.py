import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import tenant_id_ctx
from app.core.config import settings
from app.core.tenant_registry import tenant_registry
from app.services.tenant_resolver import TenantResolver

logger = logging.getLogger(__name__)

TENANT_PATH_PATTERN = re.compile(r"^/t/([^/]+)(/.*)$")


SKIP_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/api/v1/openapi.json",
    "/api/v1/platform",
)


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

        if path.startswith(SKIP_PATH_PREFIXES):
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
