"""Validate one tenant document through storage, Qdrant, and Knowledge Service.

Usage:
    python -m app.scripts.validate_knowledge_pipeline \
        --tenant vitwo --document-id UUID --query "expected phrase"
"""

import argparse
import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.repositories.document_repository import DocumentRepository
from app.services.knowledge_pipeline_diagnostics import KnowledgePipelineDiagnostics
from app.services.provider_factory import (
    embedding_provider,
    object_storage,
    vector_store,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an indexed tenant document and Knowledge Service retrieval."
    )
    parser.add_argument("--tenant", required=True, help="Exact tenant slug")
    parser.add_argument("--document-id", required=True, type=UUID)
    parser.add_argument(
        "--query", required=True, help="Text expected to retrieve the document"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if tenant is None:
            print(json.dumps({"searchable": False, "issues": ["Tenant not found."]}))
            return 2
        result = KnowledgePipelineDiagnostics(
            DocumentRepository(db),
            object_storage(),
            embedding_provider(),
            vector_store(),
        ).validate(tenant.id, args.document_id, args.query)
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0 if result.searchable else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
