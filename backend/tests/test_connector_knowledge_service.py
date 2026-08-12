import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.document_api import SearchRequest
from app.services.connector_knowledge_service import ConnectorKnowledgeService


class _CompletedKnowledgeTool:
    def __init__(self) -> None:
        self.request_id = uuid4()
        self.created_arguments = None
        self.cleared = None

    def create(self, tenant_id, user_id, tool_name, arguments):
        assert tenant_id
        assert user_id
        assert tool_name == "knowledge_search"
        self.created_arguments = arguments
        return SimpleNamespace(id=self.request_id)

    def result(self, tenant_id, request_id):
        assert tenant_id
        assert request_id == self.request_id
        return SimpleNamespace(
            id=request_id,
            status="completed",
            result={
                "results": [
                    {
                        "document_id": str(uuid4()),
                        "chunk_id": str(uuid4()),
                        "content": "Minimum authorized context",
                        "score": 0.91,
                        "metadata": {
                            "version_id": str(uuid4()),
                            "filename": "runbook.md",
                            "page_number": 3,
                        },
                    }
                ]
            },
        )

    def clear_ephemeral_payload(self, tenant_id, request_id):
        self.cleared = (tenant_id, request_id)


def test_connector_knowledge_result_is_mapped_then_cleared():
    tenant_id = uuid4()
    user_id = uuid4()
    tool = _CompletedKnowledgeTool()
    service = ConnectorKnowledgeService.__new__(ConnectorKnowledgeService)
    service.tools = tool

    response = asyncio.run(
        service.search(
            tenant_id,
            user_id,
            SearchRequest(query="Why is SAP slow?", top_k=5),
        )
    )

    assert tool.created_arguments == {"query": "Why is SAP slow?", "top_k": 5}
    assert tool.cleared == (tenant_id, tool.request_id)
    assert len(response.results) == 1
    assert response.results[0].text == "Minimum authorized context"
    assert response.results[0].title == "runbook.md"
    assert response.results[0].citation.page_number == 3
