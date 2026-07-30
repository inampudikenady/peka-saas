from datetime import UTC, datetime, timedelta
from io import BytesIO
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.connector_security import hash_connector_secret
from app.db.base import Base
from app.models.connector import ManagedConnector, ManagedConnectorStatus
from app.models.document import (
    Document, DocumentIdempotencyRecord, DocumentLifecycleStatus, DocumentVersion,
    IngestionJob, IngestionJobState, IngestionJobType, IngestionStatus,
)
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.core.tenant_context import TenantContext
from app.core.tenant_definition import TenantDefinition
from app.repositories.document_repository import DocumentRepository
from app.schemas.document_api import ConnectorDocumentMetadata
from app.services.document_ingestion_service import DocumentIngestionError, DocumentIngestionService
from app.services.object_storage import LocalFilesystemObjectStorage
from app.services.embedding_provider import (
    DeterministicFakeEmbeddingProvider,
    DisabledEmbeddingProvider,
)
from app.services.ingestion_worker import IngestionWorker
from app.services.knowledge_pipeline_diagnostics import KnowledgePipelineDiagnostics
from app.services.knowledge_service import KnowledgeFilterError, KnowledgeService
from app.services.vector_store import InMemoryVectorStore, QdrantVectorStore
from app.schemas.document_api import SearchRequest
from app.api.routes.tenant.documents import _worker_state, delete_document


@pytest.fixture()
def ingestion(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(
        slug="docs", name="Docs", display_name="Docs", status=TenantStatus.ACTIVE, timezone="UTC"
    )
    other = Tenant(
        slug="other-docs", name="Other", display_name="Other", status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    db.add_all([tenant, other]); db.flush()
    connector = ManagedConnector(
        tenant_id=tenant.id, name="Docs connector", instance_id=uuid4(), version="1.0",
        environment="test", status=ManagedConnectorStatus.CONNECTED,
        secret_hash=hash_connector_secret("secret"), registered_at=datetime.now(UTC),
        heartbeat_interval_seconds=300,
    )
    other_connector = ManagedConnector(
        tenant_id=other.id, name="Other connector", instance_id=uuid4(), version="1.0",
        environment="test", status=ManagedConnectorStatus.CONNECTED,
        secret_hash=hash_connector_secret("other-secret"), registered_at=datetime.now(UTC),
        heartbeat_interval_seconds=300,
    )
    db.add_all([connector, other_connector]); db.commit()
    repository = DocumentRepository(db)
    service = DocumentIngestionService(
        repository, LocalFilesystemObjectStorage(tmp_path), max_upload_bytes=1024 * 1024
    )
    yield db, service, repository, connector, other_connector
    db.close(); engine.dispose()


def metadata(content: bytes, operation="upsert", **overrides):
    import hashlib

    values = {
        "source_id": "filesystem-main", "document_key": "policy/security.txt",
        "relative_path": "policy/security.txt", "filename": "security.txt",
        "mime_type": "text/plain", "size_bytes": len(content),
        "content_hash": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "modified_at": datetime.now(UTC).isoformat(), "operation": operation,
        "connector_version": "1.0.0",
    }
    values.update(overrides)
    return ConnectorDocumentMetadata.model_validate(values)


def tenant_context(tenant: Tenant) -> TenantContext:
    definition = TenantDefinition(
        tenant_id=tenant.id,
        slug=tenant.slug,
        hostname=f"{tenant.slug}.test",
        enabled=True,
    )
    return TenantContext(
        tenant_id=tenant.id,
        slug=tenant.slug,
        hostname=definition.hostname,
        definition=definition,
    )


def tenant_admin(db, tenant_id):
    user = TenantUser(
        tenant_id=tenant_id,
        username=f"admin-{uuid4()}",
        email=f"{uuid4()}@example.test",
        full_name="Document Admin",
        auth_source=TenantUserAuthSource.LOCAL,
        password_hash="unused",
        is_active=True,
        role=TenantUserRole.TENANT_ADMIN,
    )
    db.add(user)
    db.commit()
    return user


def test_upsert_is_durable_verified_and_idempotent(ingestion):
    db, service, _, connector, _ = ingestion
    content = b"Password rotation is required every 90 days."
    request_metadata = metadata(content)
    first = service.accept(connector, request_metadata, "request-key-0001", BytesIO(content))
    replay = service.accept(connector, request_metadata, "request-key-0001", BytesIO(content))
    assert replay == first
    assert first.ingestion_status == "RECEIVED"
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 1
    assert db.scalar(select(func.count()).select_from(IngestionJob)) == 1
    assert db.scalar(select(func.count()).select_from(DocumentIdempotencyRecord)) == 1
    version = db.get(DocumentVersion, first.version_id)
    assert f"tenants/{connector.tenant_id}/documents/{first.document_id}/" in version.object_key
    assert service.storage.verify_hash(version.object_key, first.content_hash)
    assert service.storage.health_check() is True


def test_conflicting_idempotency_key_and_hash_mismatch_are_rejected(ingestion):
    db, service, _, connector, _ = ingestion
    content = b"first"
    service.accept(connector, metadata(content), "request-key-0002", BytesIO(content))
    with pytest.raises(DocumentIngestionError) as conflict:
        service.accept(
            connector, metadata(b"second", document_key="other.txt"),
            "request-key-0002", BytesIO(b"second"),
        )
    assert conflict.value.status_code == 409
    with pytest.raises(DocumentIngestionError):
        service.accept(
            connector, metadata(content, content_hash="sha256:" + "0" * 64),
            "request-key-0003", BytesIO(content),
        )
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 1


def test_replacement_connector_reuses_tenant_owned_indexed_document(ingestion):
    db, service, repository, connector, _ = ingestion
    replacement = ManagedConnector(
        tenant_id=connector.tenant_id,
        name="Replacement connector",
        instance_id=uuid4(),
        version="2.0",
        environment="test",
        status=ManagedConnectorStatus.CONNECTED,
        secret_hash=hash_connector_secret("replacement-secret"),
        registered_at=datetime.now(UTC),
        heartbeat_interval_seconds=300,
    )
    db.add(replacement)
    db.commit()
    content = b"Stable tenant-owned runbook content."
    first = service.accept(
        connector,
        metadata(content, source_id="old-local-source"),
        "old-connector-upload",
        BytesIO(content),
    )
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(
        repository,
        service.storage,
        DeterministicFakeEmbeddingProvider(16),
        vectors,
        "tenant-owned-dedupe-worker",
    )
    for _ in range(3):
        assert worker.run_once() is True

    connector.status = ManagedConnectorStatus.RETIRED
    connector.retired_at = datetime.now(UTC)
    db.commit()
    observed_again = service.accept(
        replacement,
        metadata(content, source_id="replacement-local-source"),
        "replacement-connector-upload",
        BytesIO(content),
    )
    db.expire_all()

    document = db.get(Document, first.document_id)
    assert observed_again.document_id == first.document_id
    assert observed_again.version_id == first.version_id
    assert observed_again.ingestion_status == "INDEXED"
    assert document.created_by_connector_id == connector.id
    assert document.last_seen_by_connector_id == replacement.id
    assert document.connector_id == replacement.id
    assert document.last_synchronized_at is not None
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 1
    assert vectors.count_points(
        connector.tenant_id, first.document_id, first.version_id
    ) > 0
    filtered = KnowledgeService(
        repository, DeterministicFakeEmbeddingProvider(16), vectors
    ).search(
        connector.tenant_id,
        SearchRequest.model_validate(
            {
                "query": "tenant-owned runbook",
                "filters": {"connector_id": str(replacement.id)},
            }
        ),
    )
    assert filtered.results


def test_failed_object_write_never_acknowledges_or_commits(ingestion):
    db, _, repository, connector, _ = ingestion

    class UnavailableStorage:
        def put_stream(self, key, stream, max_bytes):
            raise OSError("private storage detail")

        def open(self, key):
            raise AssertionError

        def delete(self, key):
            return None

        def exists(self, key):
            return False

        def verify_hash(self, key, expected_sha256):
            return False

        def health_check(self):
            return False

    service = DocumentIngestionService(repository, UnavailableStorage(), 1024 * 1024)
    content = b"must not commit"
    with pytest.raises(DocumentIngestionError) as failure:
        service.accept(connector, metadata(content), "failed-storage-key", BytesIO(content))
    assert failure.value.code.value == "STORAGE_UNAVAILABLE"
    assert db.scalar(select(func.count()).select_from(Document)) == 0
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 0


def test_filename_change_preserves_identity_and_delete_is_idempotent(ingestion):
    db, service, _, connector, _ = ingestion
    content = b"one"
    first = service.accept(connector, metadata(content), "request-key-0004", BytesIO(content))
    changed = b"two"
    second = service.accept(
        connector, metadata(changed, filename="renamed.txt", relative_path="policy/renamed.txt"),
        "request-key-0005", BytesIO(changed),
    )
    assert first.document_id == second.document_id
    delete_metadata = metadata(b"", operation="delete", size_bytes=0)
    deleted = service.accept(connector, delete_metadata, "request-key-0006", None)
    replay = service.accept(connector, delete_metadata, "request-key-0006", None)
    assert replay == deleted
    assert db.get(Document, deleted.document_id).is_deleted is True


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        ("legacy-notes.txt", "text/plain"),
        ("legacy-manual.pdf", "application/pdf"),
        (
            "legacy-policy.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "legacy-assets.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_tenant_admin_can_delete_every_supported_active_document(
    ingestion, filename, mime_type
):
    db, service, _, connector, _ = ingestion
    content = f"content for {filename}".encode()
    accepted = service.accept(
        connector,
        metadata(
            content,
            document_key=filename,
            filename=filename,
            relative_path=filename,
            mime_type=mime_type,
        ),
        f"upload-{filename}",
        BytesIO(content),
    )
    tenant = db.get(Tenant, connector.tenant_id)
    admin = tenant_admin(db, tenant.id)

    result = delete_document(
        accepted.document_id,
        connector_id=connector.id,
        tenant=tenant_context(tenant),
        user=admin,
        db=db,
    )

    assert result.is_deleted is True
    assert result.deletion_in_progress is True
    assert result.delete_eligible is False
    assert result.processing_status == "Delete pending"
    assert db.scalar(
        select(func.count()).select_from(IngestionJob).where(
            IngestionJob.document_id == accepted.document_id,
            IngestionJob.job_type == IngestionJobType.DELETE_FROM_INDEX,
        )
    ) == 1


def test_tenant_delete_is_tenant_owned_and_rejects_duplicate_cross_tenant(ingestion):
    db, service, _, connector, other_connector = ingestion
    content = b"owned document"
    accepted = service.accept(
        connector, metadata(content), "tenant-delete-ownership", BytesIO(content)
    )
    tenant = db.get(Tenant, connector.tenant_id)
    other_tenant = db.get(Tenant, other_connector.tenant_id)
    admin = tenant_admin(db, tenant.id)

    with pytest.raises(HTTPException) as wrong_tenant:
        delete_document(
            accepted.document_id,
            connector_id=connector.id,
            tenant=tenant_context(other_tenant),
            user=admin,
            db=db,
        )
    assert wrong_tenant.value.status_code == 404

    delete_document(
        accepted.document_id,
        # Connector provenance is not an ownership boundary.
        connector_id=other_connector.id,
        tenant=tenant_context(tenant),
        user=admin,
        db=db,
    )
    with pytest.raises(HTTPException) as duplicate:
        delete_document(
            accepted.document_id,
            connector_id=connector.id,
            tenant=tenant_context(tenant),
            user=admin,
            db=db,
        )
    assert duplicate.value.status_code == 409


def test_legacy_document_without_optional_version_can_be_deleted(ingestion):
    db, _, _, connector, _ = ingestion
    tenant = db.get(Tenant, connector.tenant_id)
    admin = tenant_admin(db, tenant.id)
    legacy = Document(
        tenant_id=tenant.id,
        connector_id=connector.id,
        source_id="legacy-source",
        document_key="legacy/no-version.txt",
        filename="no-version.txt",
        normalized_filename="no-version.txt",
        relative_path="legacy/no-version.txt",
        mime_type="text/plain",
        extension=".txt",
        lifecycle_status=DocumentLifecycleStatus.ACTIVE,
        is_deleted=False,
    )
    db.add(legacy)
    db.commit()

    result = delete_document(
        legacy.id,
        connector_id=connector.id,
        tenant=tenant_context(tenant),
        user=admin,
        db=db,
    )

    assert result.current_version is None
    assert result.is_deleted is True
    assert result.processing_status == "Delete pending"


def test_missing_connector_provenance_does_not_block_tenant_owned_delete(ingestion):
    db, service, _, connector, _ = ingestion
    content = b"legacy ownership"
    accepted = service.accept(
        connector, metadata(content), "invalid-legacy-owner", BytesIO(content)
    )
    tenant = db.get(Tenant, connector.tenant_id)
    admin = tenant_admin(db, tenant.id)
    document = db.get(Document, accepted.document_id)
    document.connector_id = uuid4()
    db.flush()

    deleted = delete_document(
        document.id,
        connector_id=document.connector_id,
        tenant=tenant_context(tenant),
        user=admin,
        db=db,
    )

    assert deleted.is_deleted is True
    assert deleted.processing_status == "Delete pending"


def test_failed_index_delete_remains_retryable_across_worker_restart(ingestion):
    db, service, repository, connector, _ = ingestion
    content = b"retry deletion safely"
    accepted = service.accept(
        connector, metadata(content), "retryable-delete-upload", BytesIO(content)
    )
    tenant = db.get(Tenant, connector.tenant_id)
    admin = tenant_admin(db, tenant.id)
    pipeline_job = db.scalar(
        select(IngestionJob).where(
            IngestionJob.document_id == accepted.document_id,
            IngestionJob.job_type == IngestionJobType.PARSE_DOCUMENT,
        )
    )
    pipeline_job.state = IngestionJobState.CANCELLED
    db.commit()
    delete_document(
        accepted.document_id,
        connector_id=connector.id,
        tenant=tenant_context(tenant),
        user=admin,
        db=db,
    )

    class UnavailableVectorStore(InMemoryVectorStore):
        def delete_document(self, tenant_id, document_id):
            raise OSError("temporary vector service outage")

    failed_worker = IngestionWorker(
        repository,
        service.storage,
        DeterministicFakeEmbeddingProvider(16),
        UnavailableVectorStore(),
        "delete-worker-before-restart",
    )
    assert failed_worker.run_once() is True
    delete_job = db.scalar(
        select(IngestionJob).where(
            IngestionJob.document_id == accepted.document_id,
            IngestionJob.job_type == IngestionJobType.DELETE_FROM_INDEX,
        )
    )
    version = db.get(DocumentVersion, accepted.version_id)
    assert db.get(Document, accepted.document_id).is_deleted is True
    assert delete_job.state == IngestionJobState.FAILED_RETRYABLE
    assert version.ingestion_status == IngestionStatus.DELETE_PENDING

    delete_job.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    restarted_worker = IngestionWorker(
        repository,
        service.storage,
        DeterministicFakeEmbeddingProvider(16),
        InMemoryVectorStore(),
        "delete-worker-after-restart",
    )
    assert restarted_worker.run_once() is True
    assert delete_job.state == IngestionJobState.SUCCEEDED
    assert version.ingestion_status == IngestionStatus.DELETED_FROM_INDEX


def test_returning_to_a_previous_exact_hash_reactivates_that_version(ingestion):
    db, service, _, connector, _ = ingestion
    first_content = b"version one"
    first = service.accept(
        connector, metadata(first_content), "request-key-old-1", BytesIO(first_content)
    )
    second_content = b"version two"
    service.accept(
        connector, metadata(second_content), "request-key-old-2", BytesIO(second_content)
    )

    restored = service.accept(
        connector, metadata(first_content), "request-key-old-3", BytesIO(first_content)
    )

    document = db.get(Document, first.document_id)
    assert restored.version_id == first.version_id
    assert restored.ingestion_status == "RECEIVED"
    assert document.current_version_id == first.version_id
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 2
    assert db.scalar(select(func.count()).select_from(IngestionJob).where(
        IngestionJob.version_id == first.version_id,
        IngestionJob.job_type == IngestionJobType.REINDEX_DOCUMENT,
    )) == 1


def test_tenant_scoping_and_payload_ownership_validation(ingestion):
    _, service, repository, connector, other_connector = ingestion
    content = b"tenant secret"
    accepted = service.accept(connector, metadata(content), "request-key-0007", BytesIO(content))
    assert repository.get_document(other_connector.tenant_id, accepted.document_id) is None
    with pytest.raises(ValidationError):
        ConnectorDocumentMetadata.model_validate({
            **metadata(content).model_dump(mode="json"), "tenant_id": str(other_connector.tenant_id)
        })
    with pytest.raises(ValidationError):
        metadata(content, relative_path="../secret.txt")


def test_worker_indexes_current_version_and_processes_delete(ingestion):
    db, service, repository, connector, other_connector = ingestion
    content = b"The Linux service account rotates every ninety days."
    accepted = service.accept(connector, metadata(content), "request-key-0008", BytesIO(content))
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(
        repository, service.storage, DeterministicFakeEmbeddingProvider(16), vectors, "test-worker"
    )
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True
    db.expire_all()
    version = db.get(DocumentVersion, accepted.version_id)
    assert version.ingestion_status.value == "INDEXED"
    assert repository.list_chunks(connector.tenant_id, version.id)
    assert vectors.points
    point = next(iter(vectors.points.values()))
    assert {"page", "sheet", "rows", "parser_version", "chunker_version"} <= point.payload.keys()
    assert vectors.count_points(
        connector.tenant_id, accepted.document_id, accepted.version_id
    ) == len(repository.list_chunks(connector.tenant_id, version.id))
    assert repository.list_indexed_document_titles(connector.tenant_id) == [
        "security.txt"
    ]
    assert repository.list_indexed_document_titles(other_connector.tenant_id) == []

    knowledge = KnowledgeService(
        repository, DeterministicFakeEmbeddingProvider(16), vectors
    )
    found = knowledge.search(
        connector.tenant_id,
        SearchRequest(query="Linux service account", top_k=8),
    )
    assert found.results
    assert found.results[0].source_type == "document"
    assert found.results[0].citation is not None
    diagnostics = KnowledgePipelineDiagnostics(
        repository, service.storage, DeterministicFakeEmbeddingProvider(16), vectors
    ).validate(connector.tenant_id, accepted.document_id, "Linux service account")
    assert diagnostics.searchable is True
    assert diagnostics.document_exists is True
    assert diagnostics.object_exists is True
    assert diagnostics.parsed_section_count > 0
    assert diagnostics.chunk_count == diagnostics.qdrant_point_count
    assert diagnostics.expected_chunk_retrieved is True
    isolated = KnowledgePipelineDiagnostics(
        repository, service.storage, DeterministicFakeEmbeddingProvider(16), vectors
    ).validate(
        other_connector.tenant_id, accepted.document_id, "Linux service account"
    )
    assert isolated.document_exists is False
    assert isolated.searchable is False
    assert knowledge.search(other_connector.tenant_id, SearchRequest(query="Linux")).results == []
    with pytest.raises(KnowledgeFilterError):
        knowledge.search(
            connector.tenant_id,
            SearchRequest.model_validate({
                "query": "Linux", "filters": {"connector_id": str(other_connector.id)}
            }),
        )

    delete_metadata = metadata(b"", operation="delete", size_bytes=0)
    service.accept(connector, delete_metadata, "request-key-0009", None)
    assert worker.run_once() is True
    assert vectors.points == {}
    assert knowledge.search(
        connector.tenant_id, SearchRequest(query="Linux service account")
    ).results == []


def test_dokuwiki_txt_is_detected_normalized_chunked_and_retrieved_with_code(ingestion):
    db, service, repository, connector, _ = ingestion
    content = b"""===== User id for Kohler DBA's & SAPbasis =====
  * Create Kohler DBA and SAPbasis IDs<code bash>
sudo useradd -g dba \\
  -d /home/kohlerdba \\
  -m -u 77777 kohlerdba
</code>
"""
    accepted = service.accept(
        connector,
        metadata(
            content,
            document_key="create_userid_kohler_dba_basis.txt",
            filename="create_userid_kohler_dba_basis.txt",
            relative_path="create_userid_kohler_dba_basis.txt",
        ),
        "dokuwiki-command-key",
        BytesIO(content),
    )
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(
        repository,
        service.storage,
        DeterministicFakeEmbeddingProvider(16),
        vectors,
        "dokuwiki-worker",
    )
    for _ in range(3):
        assert worker.run_once() is True
    db.expire_all()
    version = db.get(DocumentVersion, accepted.version_id)
    chunks = repository.list_chunks(connector.tenant_id, version.id)

    assert version.detected_format == "dokuwiki"
    assert version.source_format == "dokuwiki_export"
    assert version.format_detection_confidence >= 0.7
    assert chunks[0].text.startswith("## User id for Kohler DBA's & SAPbasis")
    assert "```bash" in chunks[0].text
    assert (
        "sudo useradd -g dba \\\n  -d /home/kohlerdba \\\n"
        "  -m -u 77777 kohlerdba"
    ) in chunks[0].text
    results = KnowledgeService(
        repository, DeterministicFakeEmbeddingProvider(16), vectors
    ).search(
        connector.tenant_id,
        SearchRequest(
            query="key procedures create userid kohler dba basis",
            top_k=8,
        ),
    ).results
    assert results
    assert "sudo useradd -g dba" in results[0].text


def test_reindex_reparses_historical_txt_with_current_detection_and_chunker(ingestion):
    db, service, repository, connector, _ = ingestion
    content = b"""===== Operations =====
<code bash>
systemctl status prometheus
</code>
"""
    accepted = service.accept(
        connector,
        metadata(
            content,
            document_key="historical.txt",
            filename="historical.txt",
            relative_path="historical.txt",
        ),
        "historical-reindex-key",
        BytesIO(content),
    )
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(
        repository,
        service.storage,
        DeterministicFakeEmbeddingProvider(16),
        vectors,
        "historical-reindex-worker",
    )
    for _ in range(3):
        assert worker.run_once() is True

    version = db.get(DocumentVersion, accepted.version_id)
    version.detected_format = None
    version.source_format = None
    version.format_detection_confidence = None
    version.format_detection_reason = None
    version.parser_version = "legacy"
    version.chunker_version = "legacy"
    db.commit()
    repository.enqueue_job(
        connector.tenant_id,
        accepted.document_id,
        accepted.version_id,
        IngestionJobType.REINDEX_DOCUMENT,
    )
    db.commit()

    for _ in range(4):
        assert worker.run_once() is True
    db.expire_all()
    version = db.get(DocumentVersion, accepted.version_id)
    chunks = repository.list_chunks(connector.tenant_id, version.id)

    assert version.ingestion_status == IngestionStatus.INDEXED
    assert version.detected_format == "dokuwiki"
    assert version.parser_version != "legacy"
    assert version.chunker_version == "3"
    assert len(chunks) == 1
    assert "```bash\nsystemctl status prometheus\n```" in chunks[0].text


def test_missing_embedding_provider_stops_safely_at_chunked(ingestion):
    db, service, repository, connector, _ = ingestion
    content = b"Keep parsed content when embeddings are not configured."
    accepted = service.accept(
        connector,
        metadata(
            content,
            document_key="not-configured.txt",
            filename="not-configured.txt",
            relative_path="not-configured.txt",
        ),
        "not-configured-key",
        BytesIO(content),
    )
    worker = IngestionWorker(
        repository, service.storage, DisabledEmbeddingProvider(),
        InMemoryVectorStore(), "disabled-embedding-worker",
    )
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True
    db.expire_all()
    version = db.get(DocumentVersion, accepted.version_id)
    assert version.ingestion_status == IngestionStatus.CHUNKED
    assert version.error_code == "NOT_CONFIGURED"
    assert version.failed_at is None
    assert repository.list_chunks(connector.tenant_id, version.id)


def test_new_version_replaces_old_qdrant_points(ingestion):
    db, service, repository, connector, _ = ingestion
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(
        repository, service.storage, DeterministicFakeEmbeddingProvider(16),
        vectors, "replacement-worker",
    )
    first_content = b"obsolete knowledge marker"
    first = service.accept(
        connector,
        metadata(
            first_content,
            document_key="replacement.txt",
            filename="replacement.txt",
            relative_path="replacement.txt",
        ),
        "replacement-first",
        BytesIO(first_content),
    )
    for _ in range(3):
        assert worker.run_once() is True

    second_content = b"current knowledge marker"
    second = service.accept(
        connector,
        metadata(
            second_content,
            document_key="replacement.txt",
            filename="replacement.txt",
            relative_path="replacement.txt",
        ),
        "replacement-second",
        BytesIO(second_content),
    )
    for _ in range(3):
        assert worker.run_once() is True
    db.expire_all()

    assert first.version_id != second.version_id
    assert vectors.count_points(
        connector.tenant_id, second.document_id, first.version_id
    ) == 0
    assert vectors.count_points(
        connector.tenant_id, second.document_id, second.version_id
    ) > 0
    results = KnowledgeService(
        repository, DeterministicFakeEmbeddingProvider(16), vectors
    ).search(
        connector.tenant_id,
        SearchRequest(query="current knowledge", top_k=8),
    )
    assert results.results
    assert {result.version_id for result in results.results} == {second.version_id}


@pytest.mark.skipif(
    not os.getenv("PEKA_TEST_QDRANT_URL"),
    reason="Set PEKA_TEST_QDRANT_URL to run the full Qdrant worker integration test.",
)
def test_real_qdrant_worker_version_replacement_search_and_delete(ingestion):
    import httpx

    db, service, repository, connector, _ = ingestion
    url = os.environ["PEKA_TEST_QDRANT_URL"]
    collection = f"peka_pipeline_{uuid4().hex}"
    vectors = QdrantVectorStore(url, collection, timeout=10)
    vectors.ensure_collection(16)
    worker = IngestionWorker(
        repository, service.storage, DeterministicFakeEmbeddingProvider(16),
        vectors, "real-qdrant-worker",
    )
    try:
        first_content = b"retired release procedure alpha"
        first = service.accept(
            connector,
            metadata(
                first_content,
                document_key="qdrant-e2e.txt",
                filename="qdrant-e2e.txt",
                relative_path="qdrant-e2e.txt",
            ),
            "qdrant-e2e-first",
            BytesIO(first_content),
        )
        for _ in range(3):
            assert worker.run_once() is True
        assert vectors.count_points(
            connector.tenant_id, first.document_id, first.version_id
        ) > 0
        assert KnowledgeService(
            repository, DeterministicFakeEmbeddingProvider(16), vectors
        ).search(
            connector.tenant_id, SearchRequest(query="release procedure alpha")
        ).results

        second_content = b"current release procedure omega"
        second = service.accept(
            connector,
            metadata(
                second_content,
                document_key="qdrant-e2e.txt",
                filename="qdrant-e2e.txt",
                relative_path="qdrant-e2e.txt",
            ),
            "qdrant-e2e-second",
            BytesIO(second_content),
        )
        for _ in range(3):
            assert worker.run_once() is True
        assert vectors.count_points(
            connector.tenant_id, second.document_id, first.version_id
        ) == 0
        assert vectors.count_points(
            connector.tenant_id, second.document_id, second.version_id
        ) > 0

        service.accept(
            connector,
            metadata(
                b"",
                operation="delete",
                size_bytes=0,
                document_key="qdrant-e2e.txt",
                filename="qdrant-e2e.txt",
                relative_path="qdrant-e2e.txt",
            ),
            "qdrant-e2e-delete",
            None,
        )
        assert worker.run_once() is True
        assert vectors.count_points(
            connector.tenant_id, second.document_id
        ) == 0
        assert KnowledgeService(
            repository, DeterministicFakeEmbeddingProvider(16), vectors
        ).search(
            connector.tenant_id, SearchRequest(query="release procedure omega")
        ).results == []
    finally:
        vectors.client.close()
        httpx.delete(f"{url.rstrip('/')}/collections/{collection}", timeout=10)


def test_stale_job_recovery_and_retryable_failure_are_durable(ingestion):
    db, service, repository, connector, _ = ingestion
    content = b"retryable provider content"
    accepted = service.accept(
        connector, metadata(content, document_key="retry.txt", filename="retry.txt",
                            relative_path="retry.txt"),
        "request-key-0010", BytesIO(content),
    )
    stale = db.scalar(select(IngestionJob).where(IngestionJob.version_id == accepted.version_id))
    stale.state = IngestionJobState.IN_PROGRESS
    stale.locked_at = datetime.now(UTC) - timedelta(hours=1)
    stale.locked_by = "dead-worker"; db.commit()
    assert repository.recover_stale_jobs(timedelta(minutes=10)) == 1
    assert stale.state == IngestionJobState.FAILED_RETRYABLE

    class UnavailableEmbeddings:
        name = "unavailable"; model = "unavailable"; dimension = 16
        def embed(self, texts):
            raise RuntimeError("provider raw detail must not persist")

    worker = IngestionWorker(
        repository, service.storage, UnavailableEmbeddings(), InMemoryVectorStore(), "retry-worker"
    )
    assert worker.run_once() is True  # parse
    assert worker.run_once() is True  # chunk
    assert worker.run_once() is True  # embedding failure
    failed = db.scalar(select(IngestionJob).where(
        IngestionJob.version_id == accepted.version_id,
        IngestionJob.job_type == IngestionJobType.EMBED_AND_INDEX,
    ))
    assert failed.state == IngestionJobState.FAILED_RETRYABLE
    assert failed.next_retry_at is not None
    assert "provider raw detail" not in (failed.safe_error_message or "")


def test_qdrant_failure_does_not_mark_version_indexed(ingestion):
    db, service, repository, connector, _ = ingestion
    content = b"vector failure remains recoverable"
    accepted = service.accept(
        connector,
        metadata(content, document_key="vector.txt", filename="vector.txt",
                 relative_path="vector.txt"),
        "vector-failure-key", BytesIO(content),
    )

    class FailingVectorStore(InMemoryVectorStore):
        def upsert(self, points):
            raise RuntimeError("private qdrant response")

    worker = IngestionWorker(
        repository, service.storage, DeterministicFakeEmbeddingProvider(16),
        FailingVectorStore(), "qdrant-failure-worker",
    )
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True
    db.expire_all()
    version = db.get(DocumentVersion, accepted.version_id)
    job = db.scalar(select(IngestionJob).where(
        IngestionJob.version_id == accepted.version_id,
        IngestionJob.job_type == IngestionJobType.EMBED_AND_INDEX,
    ))
    assert version.ingestion_status == IngestionStatus.CHUNKED
    assert version.indexed_at is None
    assert job.state == IngestionJobState.FAILED_RETRYABLE
    assert job.error_code == "QDRANT_UNAVAILABLE"
    assert "private qdrant response" not in (job.safe_error_message or "")


def test_retry_reuses_existing_chunks_and_does_not_duplicate_active_job(
    ingestion, monkeypatch
):
    db, service, repository, connector, _ = ingestion
    content = (" ".join(f"runbook-step-{index}" for index in range(5000))).encode()
    accepted = service.accept(
        connector,
        metadata(
            content,
            document_key="large-runbook.txt",
            filename="large-runbook.txt",
            relative_path="large-runbook.txt",
        ),
        "large-runbook-retry",
        BytesIO(content),
    )
    disabled = DisabledEmbeddingProvider()
    initial_worker = IngestionWorker(
        repository,
        service.storage,
        disabled,
        InMemoryVectorStore(),
        "initial-blocked-worker",
    )
    assert initial_worker.run_once() is True
    assert initial_worker.run_once() is True
    assert initial_worker.run_once() is True
    chunks_before = repository.list_chunks(connector.tenant_id, accepted.version_id)
    assert len(chunks_before) > 1

    first = repository.enqueue_job(
        connector.tenant_id,
        accepted.document_id,
        accepted.version_id,
        IngestionJobType.PARSE_DOCUMENT,
    )
    second = repository.enqueue_job(
        connector.tenant_id,
        accepted.document_id,
        accepted.version_id,
        IngestionJobType.PARSE_DOCUMENT,
    )
    repository.commit()
    assert first.id == second.id

    monkeypatch.setattr(
        "app.services.ingestion_worker.parser_for",
        lambda _filename: (_ for _ in ()).throw(AssertionError("must not reparse")),
    )
    vectors = InMemoryVectorStore()
    recovered_worker = IngestionWorker(
        repository,
        service.storage,
        DeterministicFakeEmbeddingProvider(16),
        vectors,
        "recovered-worker",
    )
    assert recovered_worker.run_once() is True
    assert len(repository.list_chunks(connector.tenant_id, accepted.version_id)) == len(
        chunks_before
    )
    assert recovered_worker.run_once() is True
    assert vectors.count_points(
        connector.tenant_id,
        document_id=accepted.document_id,
        version_id=accepted.version_id,
    ) == len(chunks_before)


def test_stale_worker_heartbeat_is_visible(ingestion):
    db, _, repository, _, _ = ingestion
    repository.worker_heartbeat("stale-worker", "IDLE")
    heartbeat = repository.latest_worker_heartbeat()
    heartbeat.last_seen_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    assert _worker_state(repository) == "Stale"
