"""Development-only enqueue of safe embed/index resumes for blocked documents."""

import argparse
from collections.abc import Sequence

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import (
    Document,
    DocumentAuditEvent,
    DocumentVersion,
    IngestionJobType,
    IngestionStatus,
)
from app.models.tenant import Tenant
from app.repositories.document_repository import DocumentRepository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if settings.environment.lower() in {"production", "prod"}:
        print("Refusing to enqueue development resumes in production.")
        return 2
    if not args.yes:
        print("Pass --yes to enqueue blocked current versions.")
        return 2
    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if tenant is None:
            print("Tenant not found.")
            return 1
        repository = DocumentRepository(db)
        rows = db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .where(
                Document.tenant_id == tenant.id,
                Document.is_deleted.is_(False),
                DocumentVersion.ingestion_status.in_(
                    [IngestionStatus.CHUNKED, IngestionStatus.FAILED]
                ),
                DocumentVersion.error_code.in_(
                    ["NOT_CONFIGURED", "EMBEDDING_UNAVAILABLE", "QDRANT_UNAVAILABLE"]
                ),
            )
        ).all()
        enqueued = 0
        for document, version in rows:
            if not repository.list_chunks(tenant.id, version.id):
                continue
            if repository.active_job_for_version(version.id) is not None:
                continue
            repository.enqueue_job(
                tenant.id,
                document.id,
                version.id,
                IngestionJobType.EMBED_AND_INDEX,
                "development-runtime-recovery",
            )
            repository.add(
                DocumentAuditEvent(
                    tenant_id=tenant.id,
                    document_id=document.id,
                    version_id=version.id,
                    actor_user_id=None,
                    action="DEVELOPMENT_RESUME_REQUESTED",
                    detail="Resumed from durable chunks after provider configuration.",
                )
            )
            enqueued += 1
            print(f"Queued embed/index resume: {document.filename} ({version.id})")
        repository.commit()
        print(f"Queued documents: {enqueued}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
