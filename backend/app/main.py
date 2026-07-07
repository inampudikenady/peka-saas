# app/main.py

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.routes.platform.tenants import router as platform_tenants_router
from app.api.routes.platform.auth import router as platform_auth_router
from app.core.tenant_registry import tenant_registry
from app.db.session import SessionLocal
from app.services.tenant_registry_manager import TenantRegistryManager

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
    platform_tenants_router,
    prefix=settings.api_prefix,
    tags=["platform-tenants"],
)

app.add_middleware(TenantContextMiddleware)


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


@app.get("/health")
async def health_check() -> dict[str, str]:
    logger.info("Health check requested")
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }
