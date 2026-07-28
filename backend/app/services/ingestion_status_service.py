"""Validated document-version ingestion status transitions."""

from app.models.document import DocumentVersion, IngestionStatus


class InvalidIngestionTransition(ValueError):
    pass


class IngestionStatusService:
    _allowed: dict[IngestionStatus, set[IngestionStatus]] = {
        IngestionStatus.RECEIVED: {IngestionStatus.PARSING, IngestionStatus.FAILED},
        IngestionStatus.PARSING: {IngestionStatus.PARSED, IngestionStatus.FAILED},
        IngestionStatus.PARSED: {IngestionStatus.CHUNKING, IngestionStatus.PARSING, IngestionStatus.FAILED},
        IngestionStatus.CHUNKING: {IngestionStatus.CHUNKED, IngestionStatus.FAILED},
        IngestionStatus.CHUNKED: {IngestionStatus.EMBEDDING, IngestionStatus.PARSING, IngestionStatus.FAILED},
        IngestionStatus.EMBEDDING: {IngestionStatus.INDEXING, IngestionStatus.CHUNKED, IngestionStatus.FAILED},
        IngestionStatus.INDEXING: {IngestionStatus.INDEXED, IngestionStatus.CHUNKED, IngestionStatus.FAILED},
        IngestionStatus.INDEXED: {
            IngestionStatus.PARSING, IngestionStatus.EMBEDDING,
            IngestionStatus.DELETE_PENDING, IngestionStatus.FAILED,
        },
        IngestionStatus.FAILED: {IngestionStatus.RECEIVED, IngestionStatus.PARSING, IngestionStatus.EMBEDDING},
        IngestionStatus.DELETE_PENDING: {IngestionStatus.DELETED_FROM_INDEX, IngestionStatus.FAILED},
        IngestionStatus.DELETED_FROM_INDEX: {IngestionStatus.PARSING},
    }

    def transition(self, version: DocumentVersion, target: IngestionStatus) -> None:
        if version.ingestion_status == target:
            return
        if target not in self._allowed.get(version.ingestion_status, set()):
            raise InvalidIngestionTransition(
                f"Invalid ingestion transition {version.ingestion_status.value} -> {target.value}"
            )
        version.ingestion_status = target
