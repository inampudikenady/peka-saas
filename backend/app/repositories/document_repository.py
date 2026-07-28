"""Tenant-scoped persistence operations for document ingestion."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.document import (
    Document,
    DocumentChunk,
    DocumentIdempotencyRecord,
    DocumentParsedSection,
    DocumentVersion,
    IngestionStatus,
    IngestionJob,
    IngestionJobState,
    IngestionJobType,
    IngestionWorkerHeartbeat,
)
from app.core.config import settings


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity):
        self.session.add(entity)
        return entity

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def get_logical(
        self, tenant_id: UUID, connector_id: UUID, source_id: str, document_key: str
    ) -> Document | None:
        return self.session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.connector_id == connector_id,
                Document.source_id == source_id,
                Document.document_key == document_key,
            )
        )

    def get_document(self, tenant_id: UUID, document_id: UUID) -> Document | None:
        return self.session.scalar(
            select(Document).where(Document.tenant_id == tenant_id, Document.id == document_id)
        )

    def get_document_for_update(
        self, tenant_id: UUID, document_id: UUID
    ) -> Document | None:
        return self.session.scalar(
            select(Document)
            .where(Document.tenant_id == tenant_id, Document.id == document_id)
            .with_for_update()
        )

    def get_version(self, tenant_id: UUID, version_id: UUID) -> DocumentVersion | None:
        return self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.id == version_id,
            )
        )

    def get_version_by_hash(
        self, tenant_id: UUID, document_id: UUID, content_hash: str
    ) -> DocumentVersion | None:
        return self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.content_hash == content_hash,
            )
        )

    def get_idempotency(
        self, tenant_id: UUID, connector_id: UUID, key: str
    ) -> DocumentIdempotencyRecord | None:
        now = datetime.now(timezone.utc)
        record = self.session.scalar(
            select(DocumentIdempotencyRecord).where(
                DocumentIdempotencyRecord.tenant_id == tenant_id,
                DocumentIdempotencyRecord.connector_id == connector_id,
                DocumentIdempotencyRecord.idempotency_key == key,
            )
        )
        if record is not None and record.expires_at is not None:
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                self.session.delete(record)
                self.session.flush()
                return None
        return record

    def list_documents(self, tenant_id: UUID, include_deleted: bool = False) -> list[Document]:
        query: Select[tuple[Document]] = select(Document).where(Document.tenant_id == tenant_id)
        if not include_deleted:
            query = query.where(Document.is_deleted.is_(False))
        return list(self.session.scalars(query.order_by(Document.updated_at.desc())).all())

    def list_indexed_document_titles(
        self, tenant_id: UUID, limit: int = 4
    ) -> list[str]:
        query = (
            select(Document.filename)
            .join(
                DocumentVersion,
                Document.current_version_id == DocumentVersion.id,
            )
            .where(
                Document.tenant_id == tenant_id,
                Document.is_deleted.is_(False),
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.ingestion_status == IngestionStatus.INDEXED,
                exists(
                    select(DocumentChunk.id).where(
                        DocumentChunk.tenant_id == tenant_id,
                        DocumentChunk.document_id == Document.id,
                        DocumentChunk.version_id == DocumentVersion.id,
                    )
                ),
            )
            .order_by(Document.updated_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(query).all())

    def list_versions(self, tenant_id: UUID, document_id: UUID) -> list[DocumentVersion]:
        return list(
            self.session.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.tenant_id == tenant_id,
                    DocumentVersion.document_id == document_id,
                )
                .order_by(DocumentVersion.created_at.desc())
            ).all()
        )

    def list_chunks(self, tenant_id: UUID, version_id: UUID) -> list[DocumentChunk]:
        return list(
            self.session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.version_id == version_id,
                )
                .order_by(DocumentChunk.chunk_index)
            ).all()
        )

    def list_parsed_sections(
        self, tenant_id: UUID, version_id: UUID
    ) -> list[DocumentParsedSection]:
        return list(self.session.scalars(
            select(DocumentParsedSection).where(
                DocumentParsedSection.tenant_id == tenant_id,
                DocumentParsedSection.version_id == version_id,
            ).order_by(DocumentParsedSection.section_index)
        ).all())

    def enqueue_job(
        self,
        tenant_id: UUID,
        document_id: UUID,
        version_id: UUID | None,
        job_type: IngestionJobType,
        correlation_id: str | None = None,
    ) -> IngestionJob:
        active_states = [
            IngestionJobState.PENDING, IngestionJobState.IN_PROGRESS,
            IngestionJobState.FAILED_RETRYABLE, IngestionJobState.RUNNING,
            IngestionJobState.RETRY,
        ]
        if job_type == IngestionJobType.DELETE_FROM_INDEX:
            existing = self.active_job_for_document_stage(document_id, job_type)
            if existing is not None:
                return existing
        elif version_id is not None:
            existing = self.session.scalar(select(IngestionJob).where(
                IngestionJob.version_id == version_id,
                IngestionJob.job_type == job_type,
                IngestionJob.state.in_(active_states),
            ).order_by(IngestionJob.created_at))
            if existing is not None:
                return existing
        job = IngestionJob(
            tenant_id=tenant_id, document_id=document_id, version_id=version_id,
            job_type=job_type, state=IngestionJobState.PENDING,
            correlation_id=correlation_id,
            max_attempts=settings.peka_ingestion_job_max_attempts,
        )
        self.add(job)
        return job

    def active_job_for_document_stage(
        self, document_id: UUID, job_type: IngestionJobType
    ) -> IngestionJob | None:
        return self.session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == document_id,
                IngestionJob.job_type == job_type,
                IngestionJob.state.in_(
                    [
                        IngestionJobState.PENDING,
                        IngestionJobState.IN_PROGRESS,
                        IngestionJobState.FAILED_RETRYABLE,
                        IngestionJobState.RUNNING,
                        IngestionJobState.RETRY,
                    ]
                ),
            )
            .order_by(IngestionJob.created_at)
        )

    def latest_job_for_document_stage(
        self, document_id: UUID, job_type: IngestionJobType
    ) -> IngestionJob | None:
        return self.session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == document_id,
                IngestionJob.job_type == job_type,
            )
            .order_by(IngestionJob.created_at.desc())
        )

    def active_job_for_version(self, version_id: UUID) -> IngestionJob | None:
        return self.session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.version_id == version_id,
                IngestionJob.state.in_(
                    [
                        IngestionJobState.PENDING,
                        IngestionJobState.IN_PROGRESS,
                        IngestionJobState.FAILED_RETRYABLE,
                        IngestionJobState.RUNNING,
                        IngestionJobState.RETRY,
                    ]
                ),
            )
            .order_by(IngestionJob.created_at)
        )

    def latest_worker_heartbeat(self) -> IngestionWorkerHeartbeat | None:
        return self.session.scalar(
            select(IngestionWorkerHeartbeat)
            .order_by(IngestionWorkerHeartbeat.last_seen_at.desc())
            .limit(1)
        )

    def recover_stale_jobs(self, stale_after: timedelta) -> int:
        threshold = datetime.now(timezone.utc) - stale_after
        jobs = list(self.session.scalars(select(IngestionJob).where(
            IngestionJob.state.in_([IngestionJobState.IN_PROGRESS, IngestionJobState.RUNNING]),
            IngestionJob.locked_at < threshold,
        )).all())
        for job in jobs:
            job.state = IngestionJobState.FAILED_RETRYABLE
            job.next_retry_at = datetime.now(timezone.utc)
            job.locked_at = None; job.locked_by = None
            job.error_code = "STALE_LOCK_RECOVERED"
            job.safe_error_message = "A stale worker lock was recovered."
        if jobs: self.session.commit()
        return len(jobs)

    def worker_heartbeat(
        self, worker_id: str, status: str, current_job_id: UUID | None = None
    ) -> None:
        now = datetime.now(timezone.utc)
        heartbeat = self.session.scalar(select(IngestionWorkerHeartbeat).where(
            IngestionWorkerHeartbeat.worker_id == worker_id
        ))
        if heartbeat is None:
            heartbeat = IngestionWorkerHeartbeat(
                worker_id=worker_id, last_seen_at=now, status=status,
                current_job_id=current_job_id,
            )
            self.add(heartbeat)
        else:
            heartbeat.last_seen_at = now; heartbeat.status = status
            heartbeat.current_job_id = current_job_id
        self.session.commit()

    def claim_job(self, worker_id: str) -> IngestionJob | None:
        now = datetime.now(timezone.utc)
        job = self.session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.state.in_([
                    IngestionJobState.PENDING, IngestionJobState.FAILED_RETRYABLE,
                    IngestionJobState.RETRY,
                ]),
                or_(IngestionJob.next_retry_at.is_(None), IngestionJob.next_retry_at <= now),
            )
            .order_by(IngestionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is not None:
            job.state = IngestionJobState.IN_PROGRESS
            job.locked_at = now
            job.locked_by = worker_id
            job.started_at = job.started_at or now
            job.attempts += 1
            self.session.commit()
        return job

    def delete_chunks_for_document(self, tenant_id: UUID, document_id: UUID) -> None:
        chunks = self.session.scalars(
            select(DocumentChunk).where(
                and_(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.document_id == document_id,
                )
            )
        )
        for chunk in chunks:
            self.session.delete(chunk)
