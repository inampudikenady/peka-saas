"""Lock-protected in-process ingestion runtime for the Mac-native SaaS app."""

from __future__ import annotations

import fcntl
import logging
import socket
import threading
from pathlib import Path
from typing import IO

from app.core.config import settings
from app.db.session import SessionLocal
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion_worker import IngestionWorker
from app.services.provider_factory import (
    embedding_provider,
    object_storage,
    vector_store,
)

logger = logging.getLogger(__name__)


class IngestionRuntime:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_file: IO[str] | None = None
        self.worker_id = f"in-process:{socket.gethostname()}:{id(self)}"

    def start(self) -> bool:
        if not settings.peka_ingestion_worker_enabled or self._thread is not None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="peka-ingestion-runtime",
            daemon=True,
        )
        self._thread.start()
        return True

    def notify(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
            self._thread = None
        if self._lock_file is not None:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def _run(self) -> None:
        try:
            lock_file = Path("/tmp/peka-saas-ingestion-worker.lock").open("w")
            while not self._stop.is_set():
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._lock_file = lock_file
                    break
                except BlockingIOError:
                    # Uvicorn reload starts the replacement child before the old
                    # lifespan has fully released its lock. Wait for handoff.
                    self._stop.wait(0.25)
            if self._stop.is_set():
                lock_file.close()
                return
            storage = object_storage()
            embeddings = embedding_provider()
            vectors = vector_store()
            if not vectors.health_check():
                raise RuntimeError("Qdrant health check failed")
            # Never consume durable jobs when the configured collection cannot
            # accept this worker's embedding dimension. Leaving jobs queued is
            # safer than turning a runtime configuration mismatch into one
            # failed document after another during a recovery.
            vectors.ensure_collection(embeddings.dimension)
            with SessionLocal() as session:
                repository = DocumentRepository(session)
                repository.worker_heartbeat(self.worker_id, "STARTING")
                recovered = repository.recover_orphaned_jobs_after_lock_handoff()
                if recovered:
                    logger.warning(
                        "Recovered interrupted ingestion jobs after runtime handoff",
                        extra={
                            "worker_id": self.worker_id,
                            "recovered_jobs": recovered,
                        },
                    )
            logger.info(
                "Ingestion runtime started",
                extra={
                    "worker_id": self.worker_id,
                    "runtime_mode": "in_process",
                    "embedding_provider": embeddings.name,
                    "embedding_model": embeddings.model,
                    "embedding_dimension": embeddings.dimension,
                },
            )
            while not self._stop.is_set():
                with SessionLocal() as session:
                    processed = IngestionWorker(
                        DocumentRepository(session),
                        storage,
                        embeddings,
                        vectors,
                        self.worker_id,
                    ).run_once()
                if not processed:
                    self._wake.wait(settings.peka_ingestion_worker_poll_seconds)
                    self._wake.clear()
        except Exception as exc:
            logger.exception(
                "Ingestion runtime stopped unexpectedly",
                extra={"worker_id": self.worker_id, "error_code": type(exc).__name__},
            )
        finally:
            try:
                with SessionLocal() as session:
                    DocumentRepository(session).worker_heartbeat(
                        self.worker_id, "STOPPED"
                    )
            except Exception:
                logger.exception(
                    "Could not publish ingestion runtime shutdown heartbeat"
                )
            if self._lock_file is not None:
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
                self._lock_file.close()
                self._lock_file = None
            logger.info(
                "Ingestion runtime stopped", extra={"worker_id": self.worker_id}
            )


ingestion_runtime = IngestionRuntime()
