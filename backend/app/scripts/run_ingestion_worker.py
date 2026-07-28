"""Run the PostgreSQL-backed document ingestion worker."""

import logging
import socket
import signal
import threading
from contextlib import contextmanager
from pathlib import Path

import fcntl
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion_worker import IngestionWorker
from app.services.provider_factory import embedding_provider, object_storage, vector_store


logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@contextmanager
def single_worker_lock():
    lock_path = Path("/tmp/peka-saas-ingestion-worker.lock")
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another local ingestion worker is already running.") from exc
        yield


def publish_startup_heartbeat(worker_id: str) -> None:
    """Publish before provider work begins so health never waits for the first poll."""
    with SessionLocal() as session:
        DocumentRepository(session).worker_heartbeat(worker_id, "STARTING")


def run() -> None:
    embeddings = embedding_provider()
    vectors = vector_store()
    storage = object_storage()
    database_ready = False
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
        database_ready = True
    qdrant_status = "not_configured"
    if embeddings.dimension > 0:
        try:
            if not vectors.health_check():
                raise RuntimeError("Qdrant health check failed")
            vectors.ensure_collection(embeddings.dimension)
            qdrant_status = "healthy"
        except Exception as exc:
            qdrant_status = "unavailable"
            logger.warning(
                "Ingestion worker started with Qdrant degraded",
                extra={"error_type": type(exc).__name__},
            )
    worker_id = f"{socket.gethostname()}:{id(object())}"
    publish_startup_heartbeat(worker_id)
    logger.info(
        "Ingestion worker started environment=%s worker_id=%s database=%s "
        "object_storage=%s embedding_provider=%s embedding_model=%s "
        "embedding_dimension=%s qdrant=%s qdrant_collection=%s poll_seconds=%s "
        "concurrency=%s",
        settings.environment,
        worker_id,
        "healthy" if database_ready else "unavailable",
        "healthy" if storage.health_check() else "unavailable",
        embeddings.name,
        embeddings.model,
        embeddings.dimension,
        qdrant_status,
        settings.peka_qdrant_collection,
        settings.peka_ingestion_worker_poll_seconds,
        settings.peka_ingestion_worker_concurrency,
    )
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopping.set())
    signal.signal(signal.SIGINT, lambda *_args: stopping.set())
    was_idle = False
    while not stopping.is_set():
        session = SessionLocal()
        try:
            processed = IngestionWorker(
                DocumentRepository(session), storage, embeddings, vectors, worker_id
            ).run_once()
        finally:
            session.close()
        if not processed:
            if not was_idle:
                logger.info("Ingestion worker is idle", extra={"worker_id": worker_id})
            was_idle = True
            stopping.wait(settings.peka_ingestion_worker_poll_seconds)
        else:
            was_idle = False
    with SessionLocal() as session:
        DocumentRepository(session).worker_heartbeat(worker_id, "STOPPED")
    logger.info("Ingestion worker stopped", extra={"worker_id": worker_id})


def main() -> None:
    if not settings.peka_ingestion_worker_enabled:
        raise SystemExit(
            "Ingestion worker is disabled. Set PEKA_INGESTION_WORKER_ENABLED=true."
        )
    try:
        with single_worker_lock():
            run()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
