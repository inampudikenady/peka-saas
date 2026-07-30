"""Restart-safe, stage-specific ingestion worker backed by PostgreSQL jobs."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import delete, select

from app.models.document import (
    Document, DocumentChunk, DocumentParsedSection, DocumentVersion, IngestionJob,
    IngestionJobState, IngestionJobType, IngestionStatus,
)
from app.repositories.document_repository import DocumentRepository
from app.services.document_chunker import chunk_document
from app.services.document_parsers import ParsedDocument, ParsedSection, parser_for
from app.services.embedding_provider import EmbeddingProvider, EmbeddingProviderNotConfigured
from app.services.embedding_provider import TransientEmbeddingError
from app.core.config import Settings, settings
from app.services.ingestion_status_service import IngestionStatusService
from app.services.object_storage import ObjectStorage
from app.services.vector_store import VectorPoint, VectorStore


logger = logging.getLogger(__name__)


class IngestionWorker:
    def __init__(
        self,
        repository: DocumentRepository,
        storage: ObjectStorage,
        embeddings: EmbeddingProvider,
        vectors: VectorStore,
        worker_id: str,
        config: Settings = settings,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.embeddings = embeddings
        self.vectors = vectors
        self.worker_id = worker_id
        self.config = config
        self.statuses = IngestionStatusService()

    def run_once(self) -> bool:
        recovered = self.repository.recover_stale_jobs(
            timedelta(seconds=self.config.peka_ingestion_worker_stale_job_seconds)
        )
        if recovered:
            logger.warning(
                "Recovered stale ingestion jobs",
                extra={"worker_id": self.worker_id, "recovered_jobs": recovered},
            )
        job = self.repository.claim_job(self.worker_id)
        if job is None:
            self.repository.worker_heartbeat(self.worker_id, "IDLE")
            return False
        logger.info(
            "job_claimed",
            extra={
                "job_id": str(job.id),
                "tenant_id": str(job.tenant_id),
                "document_id": str(job.document_id),
                "stage": job.job_type.value,
                "worker_id": self.worker_id,
            },
        )
        self.repository.worker_heartbeat(self.worker_id, "BUSY", job.id)
        started = time.monotonic()
        try:
            if job.job_type in {IngestionJobType.PIPELINE, IngestionJobType.PARSE_DOCUMENT}:
                self._parse(job)
            elif job.job_type == IngestionJobType.CHUNK_DOCUMENT:
                self._chunk(job)
            elif job.job_type == IngestionJobType.EMBED_AND_INDEX:
                self._embed_and_index(job)
            elif job.job_type == IngestionJobType.REINDEX_DOCUMENT:
                self._reindex(job)
            elif job.job_type == IngestionJobType.DELETE_FROM_INDEX:
                self._delete(job)
            else:
                raise ValueError("Unsupported ingestion job type")
            logger.info(
                "Ingestion stage completed",
                extra={"job_id": str(job.id), "stage": job.job_type.value,
                       "duration_ms": round((time.monotonic() - started) * 1000)},
            )
        except Exception as exc:
            self._fail(job.id, exc)
        finally:
            self.repository.worker_heartbeat(self.worker_id, "IDLE")
        return True

    def _records(self, job: IngestionJob) -> tuple[DocumentVersion, Document]:
        if job.version_id is None:
            raise ValueError("Ingestion stage is missing a document version")
        version = self.repository.get_version(job.tenant_id, job.version_id)
        document = self.repository.get_document(job.tenant_id, job.document_id)
        if version is None or document is None:
            raise ValueError("Document version no longer exists")
        return version, document

    def _succeed(self, job: IngestionJob) -> None:
        job.state = IngestionJobState.SUCCEEDED
        job.completed_at = datetime.now(timezone.utc)
        job.locked_at = None; job.locked_by = None

    def _parse(self, job: IngestionJob) -> None:
        version, document = self._records(job)
        chunks = self.repository.list_chunks(job.tenant_id, version.id)
        if chunks:
            version.ingestion_status = IngestionStatus.CHUNKED
            version.error_code = None
            version.safe_error_message = None
            self._succeed(job)
            self.repository.enqueue_job(
                job.tenant_id,
                document.id,
                version.id,
                IngestionJobType.EMBED_AND_INDEX,
                job.correlation_id,
            )
            self.repository.commit()
            logger.info(
                "Retry resumed from existing chunks",
                extra={
                    "job_id": str(job.id),
                    "version_id": str(version.id),
                    "chunk_count": len(chunks),
                },
            )
            return
        if self.repository.list_parsed_sections(job.tenant_id, version.id):
            version.ingestion_status = IngestionStatus.PARSED
            self._succeed(job)
            self.repository.enqueue_job(
                job.tenant_id,
                document.id,
                version.id,
                IngestionJobType.CHUNK_DOCUMENT,
                job.correlation_id,
            )
            self.repository.commit()
            logger.info(
                "Retry resumed from existing parsed sections",
                extra={"job_id": str(job.id), "version_id": str(version.id)},
            )
            return
        self.statuses.transition(version, IngestionStatus.PARSING)
        version.parsing_started_at = datetime.now(timezone.utc)
        self.repository.commit()
        logger.info("parser_started", extra={"job_id": str(job.id), "version_id": str(version.id)})
        with self.storage.open(version.object_key) as stream:
            parsed = parser_for(document.filename, document.mime_type).parse(stream)
        if not parsed.sections or not any(section.text.strip() for section in parsed.sections):
            raise ValueError("Parser produced no usable text")
        self.repository.session.execute(
            delete(DocumentParsedSection).where(DocumentParsedSection.version_id == version.id)
        )
        for index, section in enumerate(parsed.sections):
            self.repository.add(DocumentParsedSection(
                tenant_id=job.tenant_id, document_id=document.id, version_id=version.id,
                section_index=index, text=section.text, page_number=section.page_number,
                sheet_name=section.sheet_name, row_start=section.row_start, row_end=section.row_end,
                section_title=section.section_title,
                section_metadata={
                    **section.metadata,
                    "detected_format": parsed.detected_format,
                    "source_format": parsed.source_format,
                },
            ))
        self.statuses.transition(version, IngestionStatus.PARSED)
        version.parser_name = parsed.parser_name; version.parser_version = parsed.parser_version
        version.detected_format = parsed.detected_format
        version.source_format = parsed.source_format
        version.format_detection_confidence = parsed.detection_confidence
        version.format_detection_reason = parsed.detection_reason
        version.parsed_at = datetime.now(timezone.utc)
        self._succeed(job)
        self.repository.enqueue_job(
            job.tenant_id, document.id, version.id, IngestionJobType.CHUNK_DOCUMENT,
            job.correlation_id,
        )
        self.repository.commit()
        logger.info("parser_completed", extra={"job_id": str(job.id), "version_id": str(version.id)})

    def _chunk(self, job: IngestionJob) -> None:
        version, document = self._records(job)
        sections = self.repository.list_parsed_sections(job.tenant_id, version.id)
        parsed = ParsedDocument(
            sections=[ParsedSection(
                text=section.text, page_number=section.page_number,
                sheet_name=section.sheet_name, row_start=section.row_start,
                row_end=section.row_end, section_title=section.section_title,
                metadata=section.section_metadata,
            ) for section in sections],
            parser_name=version.parser_name or "unknown",
            parser_version=version.parser_version or "unknown",
        )
        self.statuses.transition(version, IngestionStatus.CHUNKING)
        version.chunking_started_at = datetime.now(timezone.utc)
        self.repository.commit()
        logger.info("chunking_started", extra={"job_id": str(job.id), "version_id": str(version.id)})
        chunks = chunk_document(parsed)
        if not chunks:
            raise ValueError("Chunker produced no usable chunks")
        self.repository.session.execute(
            delete(DocumentChunk).where(DocumentChunk.version_id == version.id)
        )
        for chunk in chunks:
            self.repository.add(DocumentChunk(
                id=uuid4(), tenant_id=job.tenant_id, connector_id=document.connector_id,
                source_id=document.source_id, document_id=document.id, version_id=version.id,
                chunk_index=chunk.index, chunk_key=f"{version.id}:{chunk.index}",
                text=chunk.text, token_count=chunk.token_count,
                page_number=chunk.page_number, sheet_name=chunk.sheet_name,
                row_start=chunk.row_start, row_end=chunk.row_end,
                section_title=chunk.section_title, chunk_metadata=chunk.metadata,
                qdrant_point_id=uuid5(NAMESPACE_URL, f"peka:{version.id}:{chunk.index}"),
            ))
        self.statuses.transition(version, IngestionStatus.CHUNKED)
        version.chunker_name = "markdown-block-aware"; version.chunker_version = "3"
        version.chunked_at = datetime.now(timezone.utc)
        self._succeed(job)
        self.repository.enqueue_job(
            job.tenant_id, document.id, version.id, IngestionJobType.EMBED_AND_INDEX,
            job.correlation_id,
        )
        self.repository.commit()
        logger.info("chunking_completed", extra={"job_id": str(job.id), "version_id": str(version.id), "chunk_count": len(chunks)})

    def _embed_and_index(self, job: IngestionJob) -> None:
        version, document = self._records(job)
        if document.is_deleted or document.current_version_id != version.id:
            self.vectors.delete_version(job.tenant_id, version.id)
            self._succeed(job)
            self.repository.commit()
            logger.info(
                "Inactive document version excluded from index",
                extra={"tenant_id": str(job.tenant_id), "document_id": str(document.id),
                       "version_id": str(version.id), "job_id": str(job.id)},
            )
            return
        chunks = self.repository.list_chunks(job.tenant_id, version.id)
        if not chunks:
            raise ValueError("Document version has no chunks to embed")
        self.statuses.transition(version, IngestionStatus.EMBEDDING)
        version.embedding_started_at = datetime.now(timezone.utc)
        self.repository.commit()
        logger.info("embedding_started", extra={"job_id": str(job.id), "version_id": str(version.id)})
        vectors = self.embeddings.embed([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedding provider returned an incomplete batch")
        version.embedding_completed_at = datetime.now(timezone.utc)
        logger.info("embedding_completed", extra={"job_id": str(job.id), "version_id": str(version.id), "chunk_count": len(chunks)})
        self.statuses.transition(version, IngestionStatus.INDEXING)
        version.indexing_started_at = datetime.now(timezone.utc)
        self.repository.commit()
        logger.info("qdrant_upsert_started", extra={"job_id": str(job.id), "version_id": str(version.id)})
        points = [VectorPoint(
            chunk.qdrant_point_id, vector,
            {"tenant_id": str(job.tenant_id), "connector_id": str(document.connector_id),
             "source_id": document.source_id, "document_id": str(document.id),
             "version_id": str(version.id), "chunk_id": str(chunk.id),
             "filename": document.filename, "content_hash": version.content_hash,
             "text": chunk.text, "page_number": chunk.page_number,
             "sheet_name": chunk.sheet_name, "row_start": chunk.row_start,
             "row_end": chunk.row_end, "section_title": chunk.section_title,
             "page": chunk.page_number, "sheet": chunk.sheet_name,
             "rows": {"start": chunk.row_start, "end": chunk.row_end},
             "parser_version": version.parser_version, "chunker_version": version.chunker_version,
             "embedding_model": self.embeddings.model,
             "lifecycle_status": document.lifecycle_status.value},
        ) for chunk, vector in zip(chunks, vectors, strict=True)]
        try:
            self.vectors.delete_document(job.tenant_id, document.id)
            self.vectors.upsert(points)
        except Exception as exc:
            raise QdrantUnavailableError("Qdrant indexing is unavailable") from exc
        self.statuses.transition(version, IngestionStatus.INDEXED)
        version.embedding_provider = self.embeddings.name; version.embedding_model = self.embeddings.model
        version.embedding_dimension = self.embeddings.dimension
        version.indexed_at = datetime.now(timezone.utc)
        version.indexing_completed_at = version.indexed_at
        version.error_code = None; version.safe_error_message = None; version.failed_at = None
        self._succeed(job); self.repository.commit()
        logger.info("qdrant_upsert_completed", extra={"job_id": str(job.id), "version_id": str(version.id), "point_count": len(points)})

    def _reindex(self, job: IngestionJob) -> None:
        version, document = self._records(job)
        # Reindex must rebuild from the immutable stored object. Reusing existing
        # chunks would leave documents on an older parser/chunker forever and,
        # in particular, would prevent content-aware format detection from being
        # applied to historical .txt documents.
        self.vectors.delete_document(job.tenant_id, document.id)
        self.repository.session.execute(
            delete(DocumentChunk).where(DocumentChunk.version_id == version.id)
        )
        self.repository.session.execute(
            delete(DocumentParsedSection).where(
                DocumentParsedSection.version_id == version.id
            )
        )
        version.ingestion_status = IngestionStatus.RECEIVED
        version.parser_name = None
        version.parser_version = None
        version.detected_format = None
        version.source_format = None
        version.format_detection_confidence = None
        version.format_detection_reason = None
        version.chunker_name = None
        version.chunker_version = None
        version.embedding_provider = None
        version.embedding_model = None
        version.embedding_dimension = None
        version.error_code = None
        version.safe_error_message = None
        version.failed_at = None
        self._succeed(job)
        self.repository.enqueue_job(
            job.tenant_id,
            document.id,
            version.id,
            IngestionJobType.PARSE_DOCUMENT,
            job.correlation_id,
        )
        self.repository.commit()

    def _delete(self, job: IngestionJob) -> None:
        document = self.repository.get_document(job.tenant_id, job.document_id)
        if document is None:
            raise ValueError("Document no longer exists")
        if not document.is_deleted:
            self._succeed(job)
            self.repository.commit()
            logger.info(
                "Superseded document deletion skipped",
                extra={"tenant_id": str(job.tenant_id), "document_id": str(document.id),
                       "job_id": str(job.id)},
            )
            return
        versions = list(self.repository.session.scalars(select(DocumentVersion).where(
            DocumentVersion.tenant_id == job.tenant_id,
            DocumentVersion.document_id == document.id,
        )).all())
        for version in versions:
            if version.ingestion_status != IngestionStatus.DELETED_FROM_INDEX:
                version.ingestion_status = IngestionStatus.DELETE_PENDING
        self.repository.commit()
        self.vectors.delete_document(job.tenant_id, job.document_id)
        self.repository.delete_chunks_for_document(job.tenant_id, job.document_id)
        for version in versions:
            version.ingestion_status = IngestionStatus.DELETED_FROM_INDEX
        self._succeed(job); self.repository.commit()
        logger.info("Document index deletion completed", extra={"job_id": str(job.id),
                    "document_id": str(job.document_id)})

    def _fail(self, job_id, exc: Exception) -> None:
        self.repository.rollback()
        job = self.repository.session.get(IngestionJob, job_id)
        if job is None:
            raise exc
        if isinstance(exc, EmbeddingProviderNotConfigured):
            job.error_code = "NOT_CONFIGURED"
            job.safe_error_message = "Embedding provider is not configured."
        elif isinstance(exc, TransientEmbeddingError):
            job.error_code = "EMBEDDING_UNAVAILABLE"
            job.safe_error_message = "Embedding endpoint is currently unavailable."
        elif isinstance(exc, QdrantUnavailableError):
            job.error_code = "QDRANT_UNAVAILABLE"
            job.safe_error_message = "Qdrant is currently unavailable."
        else:
            job.error_code = type(exc).__name__[:100]
            job.safe_error_message = "Document processing failed safely."
        permanent = isinstance(
            exc, (ValueError, FileNotFoundError, EmbeddingProviderNotConfigured)
        )
        if permanent or job.attempts >= job.max_attempts:
            job.state = IngestionJobState.FAILED_PERMANENT
        else:
            job.state = IngestionJobState.FAILED_RETRYABLE
            jitter = random.SystemRandom().uniform(0, 1)
            job.next_retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=min(
                    self.config.peka_ingestion_retry_max_seconds,
                    self.config.peka_ingestion_retry_base_seconds
                    * (2 ** max(0, job.attempts - 1)),
                )
                + jitter
            )
        job.locked_at = None; job.locked_by = None
        if (
            job.version_id is not None
            and job.job_type != IngestionJobType.DELETE_FROM_INDEX
        ):
            version = self.repository.get_version(job.tenant_id, job.version_id)
            if version is not None:
                if isinstance(
                    exc,
                    (
                        EmbeddingProviderNotConfigured,
                        TransientEmbeddingError,
                        QdrantUnavailableError,
                    ),
                ):
                    version.ingestion_status = IngestionStatus.CHUNKED
                    version.failed_at = None
                else:
                    version.ingestion_status = IngestionStatus.FAILED
                    version.failed_at = datetime.now(timezone.utc)
                version.error_code = job.error_code
                version.safe_error_message = job.safe_error_message
        self.repository.commit()
        logger.error(
            "Document ingestion stage failed job_id=%s stage=%s error_code=%s "
            "blocking_reason=%s",
            job.id,
            job.job_type.value,
            job.error_code,
            job.safe_error_message,
        )


class QdrantUnavailableError(RuntimeError):
    """Safe worker-facing signal for a temporarily unavailable vector store."""
