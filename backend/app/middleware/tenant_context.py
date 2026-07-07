import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import tenant_id_ctx
from app.core.tenant_registry import tenant_registry
from app.services.tenant_resolver import TenantResolver

logger = logging.getLogger(__name__)


SKIP_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/api/v1/openapi.json",
    "/api/v1/platform",
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.resolver = TenantResolver(tenant_registry)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path.startswith(SKIP_PATH_PREFIXES):
            return await call_next(request)

        host = request.headers.get("host", "")
        tenant_context = self.resolver.resolve_from_host(host)
        token = None

        if tenant_context is not None:
            request.state.tenant_context = tenant_context
            request.state.tenant_id = tenant_context.tenant_id
            token = tenant_id_ctx.set(str(tenant_context.tenant_id))

            logger.info(
                "Resolved tenant '%s' from host '%s'",
                tenant_context.slug,
                tenant_context.hostname,
            )
        else:
            logger.warning("No tenant found for host '%s'", host)

        try:
            return await call_next(request)
        finally:
            if token is not None:
                tenant_id_ctx.reset(token)
