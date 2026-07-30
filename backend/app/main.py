# app/main.py

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.routes.platform.tenants import router as platform_tenants_router
from app.api.routes.platform.auth import router as platform_auth_router
from app.api.routes.platform.users import router as platform_users_router
from app.api.routes.platform.settings import router as platform_settings_router
from app.api.routes.platform.development_email import (
    router as platform_development_email_router,
)
from app.api.routes.tenant.auth import router as tenant_auth_router
from app.core.tenant_registry import tenant_registry
from app.db.session import SessionLocal
from app.services.tenant_registry_manager import TenantRegistryManager
from app.api.routes.tenant.security import router as tenant_security_router
from app.api.routes.tenant.users import router as tenant_users_router
from app.api.routes.connectors import (
    connector_registration_validation_handler,
    router as connectors_router,
)
from app.api.routes.platform.connectors import router as platform_connectors_router
from app.api.routes.tenant.connectors import router as tenant_connectors_router
from app.api.routes.tenant.documents import router as tenant_documents_router
from app.api.routes.tenant.ai_answer import router as tenant_ai_answer_router
from app.api.routes.tenant.ai_conversations import router as tenant_ai_conversations_router
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.tenant_repository import TenantRepository
from app.services.connector_service import ConnectorService
from sqlalchemy import func, select, text as sql_text
from app.models.document import IngestionJob, IngestionJobState, IngestionWorkerHeartbeat
from app.services.document_parsers import parser_registry
from app.services.provider_factory import object_storage
from app.services.knowledge_initialization import initialize_knowledge_dependencies
from app.services.knowledge_runtime_health import embedding_health, qdrant_health
from app.services.chat_runtime_health import chat_health
from app.schemas.ai_answer import AIAnswerErrorCode, AIAnswerErrorResponse
from app.services.ingestion_runtime import ingestion_runtime

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
    platform_development_email_router,
    prefix=settings.api_prefix,
    tags=["platform-development-email"],
)

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
app.include_router(tenant_documents_router, prefix=settings.api_prefix, tags=["tenant-documents"])
app.include_router(tenant_ai_answer_router, prefix=settings.api_prefix, tags=["tenant-ai"])
app.include_router(
    tenant_ai_conversations_router,
    prefix=settings.api_prefix,
    tags=["tenant-ai-conversations"],
)
app.add_middleware(TenantContextMiddleware)

maintenance_task: asyncio.Task | None = None


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    if request.url.path.endswith((
        f"{settings.api_prefix}/tenant/ai/answer",
        f"{settings.api_prefix}/tenant/ai/answer/stream",
    )):
        body = AIAnswerErrorResponse(
            code=AIAnswerErrorCode.INVALID_QUERY,
            message="The AI answer request is invalid.",
            request_id=request_id_ctx.get(),
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))
    return await connector_registration_validation_handler(request, exc)


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
    initialize_knowledge_dependencies()
    if ingestion_runtime.start():
        logger.info("Mac-native in-process ingestion runtime enabled")
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
    ingestion_runtime.stop()


@app.get("/health")
async def health_check() -> dict[str, str]:
    logger.info("Health check requested")
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/health/knowledge")
def knowledge_health_check() -> dict:
    """Optional knowledge-pipeline diagnostics without impacting core health."""
    checks: dict[str, dict[str, object]] = {}
    reasons: list[str] = []
    db = SessionLocal()
    try:
        db.execute(sql_text("SELECT 1"))
        checks["postgresql"] = {"status": "healthy"}
        now = datetime.now(timezone.utc)
        heartbeat = db.scalar(
            select(IngestionWorkerHeartbeat).order_by(
                IngestionWorkerHeartbeat.last_seen_at.desc()
            ).limit(1)
        )
        if heartbeat is None:
            checks["ingestion_worker"] = {
                "status": "degraded",
                "state": "not_running",
                "last_heartbeat": None,
                "reason": "Worker has not published a heartbeat.",
            }
            reasons.append("worker not running")
        else:
            seen = heartbeat.last_seen_at
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            age = (now - seen).total_seconds()
            healthy_worker = (
                age <= settings.peka_ingestion_worker_heartbeat_stale_seconds
                and heartbeat.status != "STOPPED"
            )
            checks["ingestion_worker"] = {
                "status": "healthy" if healthy_worker else "degraded",
                "state": heartbeat.status,
                "last_heartbeat": seen.isoformat(),
                "last_seen_seconds_ago": round(age),
                "reason": None if healthy_worker else "Worker heartbeat is stale or stopped.",
            }
            if not healthy_worker:
                reasons.append("worker heartbeat stale")
        queued_count = db.scalar(
            select(func.count()).select_from(IngestionJob).where(
                IngestionJob.state.in_(
                    [
                        IngestionJobState.PENDING,
                        IngestionJobState.FAILED_RETRYABLE,
                        IngestionJobState.RETRY,
                    ]
                )
            )
        ) or 0
        stale_count = db.scalar(select(func.count()).select_from(IngestionJob).where(
            IngestionJob.state.in_([IngestionJobState.IN_PROGRESS, IngestionJobState.RUNNING]),
            IngestionJob.locked_at
            < now - timedelta(seconds=settings.peka_ingestion_worker_stale_job_seconds),
        )) or 0
        checks["jobs"] = {
            "status": "degraded" if stale_count else "healthy",
            "queued_count": queued_count,
            "stale_count": stale_count,
            "reason": "Stale ingestion jobs require recovery." if stale_count else None,
        }
        if stale_count:
            reasons.append("stale ingestion jobs")
    except Exception:
        checks["postgresql"] = {"status": "unavailable"}
        checks["ingestion_worker"] = {"status": "unavailable", "reason": "Database unavailable."}
        checks["jobs"] = {"status": "unavailable", "reason": "Database unavailable."}
        reasons.append("PostgreSQL unavailable")
    finally:
        db.close()
    try:
        checks["object_storage"] = {
            "status": "healthy" if object_storage().health_check() else "unavailable"
        }
    except Exception:
        checks["object_storage"] = {"status": "unavailable"}
    checks["parsers"] = {
        "status": "healthy", "formats": parser_registry.availability()
    }
    checks["embedding_provider"] = embedding_health()
    checks["qdrant"] = qdrant_health()
    checks["chat_provider"] = chat_health()
    for name in ("embedding_provider", "qdrant", "chat_provider"):
        check = checks[name]
        if check["status"] != "healthy" and check.get("reason"):
            reasons.append(str(check["reason"]))
    core_unavailable = checks["postgresql"]["status"] == "unavailable"
    unavailable = any(check["status"] == "unavailable" for check in checks.values())
    degraded = any(
        check["status"] in {"degraded", "not_configured"} for check in checks.values()
    )
    overall = (
        "unavailable"
        if core_unavailable
        else "degraded"
        if unavailable or degraded
        else "healthy"
    )
    ingestion_dependencies = (
        "postgresql",
        "ingestion_worker",
        "jobs",
        "object_storage",
        "parsers",
        "embedding_provider",
        "qdrant",
    )
    ingestion_state = (
        "unavailable"
        if checks["postgresql"]["status"] == "unavailable"
        else "degraded"
        if any(checks[name]["status"] != "healthy" for name in ingestion_dependencies)
        else "healthy"
    )
    retrieval_state = (
        "healthy"
        if all(
            checks[name]["status"] == "healthy"
            for name in ("postgresql", "embedding_provider", "qdrant")
        )
        else "unavailable"
    )
    return {
        "status": overall,
        "overall_knowledge_state": overall,
        "ingestion_state": ingestion_state,
        "retrieval_state": retrieval_state,
        "chat_state": checks["chat_provider"]["status"],
        "reasons": reasons,
        "checks": checks,
    }
