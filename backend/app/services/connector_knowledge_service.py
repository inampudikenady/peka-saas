"""Retrieve tenant knowledge through the connector's outbound request channel."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.document_api import (
    KnowledgeCitation,
    KnowledgeResult,
    SearchRequest,
    SearchResponse,
)
from app.services.knowledge_service import KnowledgeFilterError
from app.services.operational_tool_service import (
    OperationalToolService,
    OperationalToolUnavailable,
)


class ConnectorKnowledgeService:
    def __init__(self, db: Session) -> None:
        self.tools = OperationalToolService(db)

    async def search(
        self, tenant_id: UUID, user_id: UUID, request: SearchRequest
    ) -> SearchResponse:
        arguments: dict[str, object] = {
            "query": request.query,
            "top_k": request.top_k,
        }
        if request.filters.document_id:
            arguments["document_id"] = str(request.filters.document_id)
        if request.filters.connector_id or request.filters.source_id:
            raise KnowledgeFilterError(
                "Connector and source filters are not supported by local knowledge retrieval"
            )
        tool_request = self.tools.create(
            tenant_id, user_id, "knowledge_search", arguments
        )
        while True:
            current = self.tools.result(tenant_id, tool_request.id)
            if current.status == "completed":
                raw = dict(current.result or {})
                self.tools.clear_ephemeral_payload(tenant_id, current.id)
                return SearchResponse(results=self._results(raw))
            if current.status == "failed":
                self.tools.clear_ephemeral_payload(tenant_id, current.id)
                raise OperationalToolUnavailable(
                    current.error_message or "Local knowledge retrieval failed."
                )
            if current.status == "expired":
                self.tools.clear_ephemeral_payload(tenant_id, current.id)
                raise OperationalToolUnavailable(
                    "The active connector did not answer the knowledge request in time."
                )
            await asyncio.sleep(0.25)

    @staticmethod
    def _results(payload: dict) -> list[KnowledgeResult]:
        results: list[KnowledgeResult] = []
        for item in payload.get("results") or []:
            metadata = dict(item.get("metadata") or {})
            try:
                document_id = UUID(str(item["document_id"]))
                chunk_id = UUID(str(item["chunk_id"]))
                version_id = UUID(str(metadata["version_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            results.append(
                KnowledgeResult(
                    knowledge_id=f"document:{chunk_id}",
                    text=str(item.get("content") or ""),
                    score=float(item.get("score") or 0),
                    document_id=document_id,
                    version_id=version_id,
                    chunk_id=chunk_id,
                    title=str(metadata.get("filename") or "Document"),
                    citation=KnowledgeCitation(
                        page_number=metadata.get("page_number"),
                        sheet_name=metadata.get("sheet_name"),
                        row_start=metadata.get("row_start"),
                        row_end=metadata.get("row_end"),
                        section_title=metadata.get("section_title"),
                    ),
                    metadata=metadata,
                )
            )
        return results
