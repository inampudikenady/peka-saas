"""Transactional document acceptance and tombstone handling."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.models.connector import ManagedConnector
from app.models.document import (
    Document,
    DocumentIdempotencyRecord,
    DocumentLifecycleStatus,
    DocumentVersion,
    IngestionJobType,
    IngestionStatus,
    StorageStatus,
)
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import ConnectorDocumentAcknowledgement, ConnectorDocumentMetadata
from app.schemas.document_api import DocumentErrorCode
from app.services.object_storage import ObjectStorage, ObjectTooLargeError
from app.services.ingestion_runtime import ingestion_runtime


logger = logging.getLogger(__name__)


class DocumentIngestionError(ValueError):
    def __init__(
        self,
        code: DocumentErrorCode,
        message: str,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class DocumentIngestionService:
    def __init__(
        self,
        repository: DocumentRepository,
        storage: ObjectStorage,
        max_upload_bytes: int,
        idempotency_hours: int = 24,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.max_upload_bytes = max_upload_bytes
        self.idempotency_hours = idempotency_hours

    @staticmethod
    def _fingerprint(connector_id, metadata: ConnectorDocumentMetadata) -> str:
        values = metadata.model_dump(mode="json")
        values["connector_id"] = str(connector_id)
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _replay(
        self, connector: ManagedConnector, key: str, fingerprint: str
    ) -> ConnectorDocumentAcknowledgement | None:
        record = self.repository.get_idempotency(connector.tenant_id, connector.id, key)
        if record is None:
            return None
        if record.request_fingerprint != fingerprint:
            raise DocumentIngestionError(
                DocumentErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency-Key was already used for a different request.", 409
            )
        return ConnectorDocumentAcknowledgement.model_validate(record.response_payload)

    def _record_idempotency(
        self,
        connector: ManagedConnector,
        key: str,
        fingerprint: str,
        metadata: ConnectorDocumentMetadata,
        response: ConnectorDocumentAcknowledgement,
    ) -> None:
        self.repository.add(
            DocumentIdempotencyRecord(
                tenant_id=connector.tenant_id,
                connector_id=connector.id,
                idempotency_key=key,
                operation=metadata.operation,
                request_fingerprint=fingerprint,
                document_id=response.document_id,
                version_id=response.version_id,
                response_payload=response.model_dump(mode="json"),
                http_status=201,
                status="ACCEPTED",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=self.idempotency_hours),
            )
        )

    def accept(
        self,
        connector: ManagedConnector,
        metadata: ConnectorDocumentMetadata,
        idempotency_key: str,
        stream: BinaryIO | None,
        upload_mime_type: str | None = None,
    ) -> ConnectorDocumentAcknowledgement:
        fingerprint = self._fingerprint(connector.id, metadata)
        if replay := self._replay(connector, idempotency_key, fingerprint):
            logger.info(
                "Document delivery replayed",
                extra={"connector_id": str(connector.id), "document_id": str(replay.document_id)},
            )
            return replay
        if metadata.operation == "delete":
            return self._delete(connector, metadata, idempotency_key, fingerprint)
        if metadata.content_hash is None or metadata.modified_at is None:
            raise DocumentIngestionError(
                DocumentErrorCode.INVALID_DOCUMENT_METADATA,
                "An upsert requires a content hash and modification timestamp.",
            )
        content_hash = metadata.content_hash.lower()
        modified_at = metadata.modified_at
        if stream is None:
            raise DocumentIngestionError(
                DocumentErrorCode.VALIDATION_FAILED, "A file is required for an upsert."
            )
        if upload_mime_type and upload_mime_type != metadata.mime_type:
            raise DocumentIngestionError(
                DocumentErrorCode.MIME_MISMATCH,
                "The uploaded file MIME type does not match document metadata.",
            )
        if metadata.size_bytes > self.max_upload_bytes:
            raise DocumentIngestionError(
                DocumentErrorCode.SIZE_MISMATCH,
                "The document exceeds the configured size limit.", 413
            )

        now = datetime.now(timezone.utc)
        document = self.repository.get_logical(
            connector.tenant_id, metadata.source_id, metadata.document_key
        )
        if document is None:
            document = Document(
                id=uuid4(), tenant_id=connector.tenant_id, connector_id=connector.id,
                created_by_connector_id=connector.id,
                last_seen_by_connector_id=connector.id,
                last_synchronized_at=now,
                source_id=metadata.source_id, document_key=metadata.document_key,
                filename=metadata.filename, normalized_filename=metadata.filename.casefold(),
                relative_path=metadata.relative_path, mime_type=metadata.mime_type,
                extension=Path(metadata.filename).suffix.lower(),
                lifecycle_status=DocumentLifecycleStatus.ACTIVE, is_deleted=False,
            )
            self.repository.add(document)
            self.repository.flush()
        else:
            document.connector_id = connector.id
            document.last_seen_by_connector_id = connector.id
            document.last_synchronized_at = now
            document.source_id = metadata.source_id
        existing = self.repository.get_version_by_hash(
            connector.tenant_id, document.id, content_hash
        )
        document.filename = metadata.filename
        document.normalized_filename = metadata.filename.casefold()
        document.relative_path = metadata.relative_path
        document.mime_type = metadata.mime_type
        document.extension = Path(metadata.filename).suffix.lower()
        document.lifecycle_status = DocumentLifecycleStatus.ACTIVE
        document.is_deleted = False
        document.deleted_at = None
        version_id = uuid4()
        safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", metadata.filename)
        object_key = (
            f"tenants/{connector.tenant_id}/documents/"
            f"{document.id}/versions/{version_id}/{safe_filename}"
        )
        try:
            stored = self.storage.put_stream(object_key, stream, self.max_upload_bytes)
        except ObjectTooLargeError as exc:
            self.repository.rollback()
            raise DocumentIngestionError(
                DocumentErrorCode.SIZE_MISMATCH,
                "The uploaded document exceeds the configured size limit.", 413,
            ) from exc
        except Exception as exc:
            self.repository.rollback()
            raise DocumentIngestionError(
                DocumentErrorCode.STORAGE_UNAVAILABLE,
                "Document storage is temporarily unavailable.", 503,
            ) from exc
        if stored.size_bytes != metadata.size_bytes:
            self.storage.delete(object_key)
            self.repository.rollback()
            raise DocumentIngestionError(
                DocumentErrorCode.SIZE_MISMATCH,
                "Declared document size does not match uploaded bytes.",
            )
        if stored.sha256.lower() != content_hash:
            self.storage.delete(object_key)
            self.repository.rollback()
            raise DocumentIngestionError(
                DocumentErrorCode.HASH_MISMATCH,
                "Declared SHA-256 does not match uploaded bytes.",
            )
        logger.info(
            "document_stored",
            extra={"tenant_id": str(connector.tenant_id),
                   "connector_id": str(connector.id), "document_id": str(document.id)},
        )
        if existing is not None:
            self.storage.delete(object_key)
            requires_reindex = (
                document.current_version_id != existing.id
                or existing.ingestion_status != IngestionStatus.INDEXED
            )
            document.current_version_id = existing.id
            if requires_reindex:
                existing.ingestion_status = IngestionStatus.RECEIVED
                existing.error_code = None
                existing.safe_error_message = None
                existing.failed_at = None
                self.repository.enqueue_job(
                    connector.tenant_id, document.id, existing.id,
                    IngestionJobType.REINDEX_DOCUMENT, idempotency_key,
                )
            response = ConnectorDocumentAcknowledgement(
                document_id=document.id, version_id=existing.id,
                content_hash=existing.content_hash,
                ingestion_status=(
                    IngestionStatus.RECEIVED.value
                    if requires_reindex else existing.ingestion_status.value
                ),
            )
            self._record_idempotency(
                connector, idempotency_key, fingerprint, metadata, response
            )
            self.repository.commit()
            ingestion_runtime.notify()
            return response
        version = DocumentVersion(
            id=version_id, document_id=document.id, tenant_id=connector.tenant_id,
            connector_id=connector.id, content_hash=stored.sha256.lower(),
            size_bytes=stored.size_bytes, modified_at=modified_at,
            object_key=stored.key, storage_status=StorageStatus.STORED,
            ingestion_status=IngestionStatus.RECEIVED, received_at=now,
            stored_at=now, queued_at=now,
        )
        document.current_version_id = version.id
        self.repository.add(version)
        # The idempotency row and job both reference this immutable version.
        # Flush it first because these models intentionally avoid ORM relationship
        # coupling and PostgreSQL must see the referenced key before dependants.
        self.repository.flush()
        self.repository.enqueue_job(
            connector.tenant_id, document.id, version.id,
            IngestionJobType.PARSE_DOCUMENT, idempotency_key,
        )
        response = ConnectorDocumentAcknowledgement(
            document_id=document.id, version_id=version.id,
            content_hash=stored.sha256.lower(), ingestion_status=IngestionStatus.RECEIVED.value,
        )
        self._record_idempotency(connector, idempotency_key, fingerprint, metadata, response)
        try:
            self.repository.commit()
        except IntegrityError as exc:
            self.repository.rollback()
            self.storage.delete(object_key)
            constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            logger.error(
                "Document metadata commit rejected (internal_reason=integrity_error, constraint=%s)",
                constraint_name or "unknown",
                extra={"tenant_id": str(connector.tenant_id),
                       "connector_id": str(connector.id),
                       "document_id": str(document.id)},
            )
            raise DocumentIngestionError(
                DocumentErrorCode.STORAGE_UNAVAILABLE,
                "The document could not be committed safely.", 503,
            ) from exc
        except Exception:
            self.repository.rollback()
            self.storage.delete(object_key)
            raise
        logger.info(
            "job_queued",
            extra={
                "tenant_id": str(connector.tenant_id), "connector_id": str(connector.id),
                "document_id": str(document.id), "version_id": str(version.id),
                "stage": IngestionJobType.PARSE_DOCUMENT.value,
            },
        )
        ingestion_runtime.notify()
        return response

    def _delete(
        self,
        connector: ManagedConnector,
        metadata: ConnectorDocumentMetadata,
        idempotency_key: str,
        fingerprint: str,
    ) -> ConnectorDocumentAcknowledgement:
        now = datetime.now(timezone.utc)
        document = self.repository.get_logical(
            connector.tenant_id, metadata.source_id, metadata.document_key
        )
        if document is None:
            raise DocumentIngestionError(
                DocumentErrorCode.DOCUMENT_NOT_FOUND,
                "The document was not found for this connector.", 404,
            )
        if not document.is_deleted:
            document.connector_id = connector.id
            document.last_seen_by_connector_id = connector.id
            document.last_synchronized_at = now
            document.lifecycle_status = DocumentLifecycleStatus.DELETED
            document.is_deleted = True
            document.deleted_at = now
            self.repository.enqueue_job(
                connector.tenant_id, document.id, None,
                IngestionJobType.DELETE_FROM_INDEX, idempotency_key,
            )
        response = ConnectorDocumentAcknowledgement(
            document_id=document.id, version_id=None, content_hash=None,
            ingestion_status="DELETE_RECEIVED",
        )
        self._record_idempotency(connector, idempotency_key, fingerprint, metadata, response)
        self.repository.commit()
        ingestion_runtime.notify()
        logger.info(
            "Document deletion accepted",
            extra={
                "tenant_id": str(connector.tenant_id), "connector_id": str(connector.id),
                "document_id": str(document.id),
            },
        )
        return response
