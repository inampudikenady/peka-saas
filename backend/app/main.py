# app/main.py

import logging
import uuid

from fastapi import FastAPI, Request

from app.core.config import settings
from app.core.logging import configure_logging, request_id_ctx

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
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


@app.get("/health")
async def health_check() -> dict[str, str]:
    logger.info("Health check requested")
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }