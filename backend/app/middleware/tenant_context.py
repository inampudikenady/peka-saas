import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import tenant_id_ctx
from app.db.session import SessionLocal
from app.repositories.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


SKIP_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/api/v1/openapi.json",
    "/api/v1/platform",
)


def extract_subdomain(host: str) -> Optional[str]:
    hostname = host.split(":", 1)[0].lower()

    if hostname in {"localhost", "127.0.0.1"}:
        return None

    parts = hostname.split(".")

    if len(parts) < 3:
        return None

    return hostname


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path.startswith(SKIP_PATH_PREFIXES):
            return await call_next(request)

        host = request.headers.get("host", "")
        subdomain = extract_subdomain(host)

        token = None

        if subdomain:
            db = SessionLocal()
            try:
                repository = TenantRepository(db)
                tenant = repository.get_by_subdomain(subdomain)

                if tenant:
                    request.state.tenant = tenant
                    request.state.tenant_id = tenant.id
                    token = tenant_id_ctx.set(str(tenant.id))
                    logger.info("Resolved tenant '%s' from host '%s'", tenant.slug, host)
                else:
                    logger.warning("No tenant found for host '%s'", host)
            finally:
                db.close()

        try:
            return await call_next(request)
        finally:
            if token:
                tenant_id_ctx.reset(token)
