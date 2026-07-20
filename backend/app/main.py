# app/main.py

import asyncio
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.routes.platform.tenants import router as platform_tenants_router
from app.api.routes.platform.auth import router as platform_auth_router
from app.api.routes.platform.users import router as platform_users_router
from app.api.routes.platform.settings import router as platform_settings_router
from app.api.routes.tenant.auth import router as tenant_auth_router
from app.core.tenant_registry import tenant_registry
from app.db.session import SessionLocal
from app.services.tenant_registry_manager import TenantRegistryManager
from app.api.routes.tenant.security import router as tenant_security_router
from app.api.routes.tenant.users import router as tenant_users_router
from app.api.routes.connectors import router as connectors_router
from app.api.routes.platform.connectors import router as platform_connectors_router
from app.api.routes.tenant.connectors import router as tenant_connectors_router
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.tenant_repository import TenantRepository
from app.services.connector_service import ConnectorService

from app.core.exceptions import (
    TenantAlreadyExistsError,
    TenantDomainAlreadyExistsError,
    TenantNotFoundError,
)
from app.core.config import settings
from app.core.logging import configure_logging, request_id_ctx
from app.middleware.tenant_context import TenantContextMiddleware

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)


app.include_router(
    platform_auth_router,
    prefix=settings.api_prefix,
    tags=["platform-auth"],
)

app.include_router(
    platform_users_router,
    prefix=settings.api_prefix,
    tags=["platform-users"],
)
app.include_router(platform_settings_router, prefix=settings.api_prefix, tags=["platform-settings"])

app.include_router(
    platform_tenants_router,
    prefix=settings.api_prefix,
    tags=["platform-tenants"],
)

app.include_router(
    tenant_auth_router,
    prefix=settings.api_prefix,
    tags=["tenant-auth"],
)

app.include_router(
    tenant_security_router,
    prefix=settings.api_prefix,
    tags=["tenant-security"],
)
app.include_router(tenant_users_router, prefix=settings.api_prefix, tags=["tenant-users"])
app.include_router(connectors_router, prefix=settings.api_prefix, tags=["connectors"])
app.include_router(platform_connectors_router, prefix=settings.api_prefix, tags=["platform-connectors"])
app.include_router(tenant_connectors_router, prefix=settings.api_prefix, tags=["tenant-connectors"])
app.add_middleware(TenantContextMiddleware)

maintenance_task: asyncio.Task | None = None


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    if request.url.path == f"{settings.api_prefix}/connectors/register":
        return JSONResponse(status_code=400, content={"detail": "Malformed connector registration request."})
    return await request_validation_exception_handler(request, exc)


async def connector_maintenance_loop() -> None:
    while True:
        await asyncio.sleep(settings.connector_maintenance_interval_seconds)
        db = SessionLocal()
        try:
            ConnectorService(ConnectorRepository(db), TenantRepository(db)).maintenance()
        except Exception:
            db.rollback()
            logger.exception("Connector maintenance failed")
        finally:
            db.close()


@app.exception_handler(TenantAlreadyExistsError)
async def tenant_already_exists_handler(
    request: Request,
    exc: TenantAlreadyExistsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc)},
    )


@app.exception_handler(TenantDomainAlreadyExistsError)
async def tenant_domain_already_exists_handler(
    request: Request,
    exc: TenantDomainAlreadyExistsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc)},
    )


@app.exception_handler(TenantNotFoundError)
async def tenant_not_found_handler(
    request: Request,
    exc: TenantNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc)},
    )


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    token = request_id_ctx.set(request_id)

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_ctx.reset(token)


@app.on_event("startup")
async def startup_event() -> None:
    global maintenance_task
    logger.info(
        "Starting %s %s in %s mode",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )

    db = SessionLocal()
    try:
        TenantRegistryManager(tenant_registry).load(db)
    finally:
        db.close()
    maintenance_task = asyncio.create_task(connector_maintenance_loop())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global maintenance_task
    if maintenance_task is not None:
        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            pass
        maintenance_task = None


@app.get("/health")
async def health_check() -> dict[str, str]:
    logger.info("Health check requested")
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }
