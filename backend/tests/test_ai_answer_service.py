import asyncio
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.schemas.ai_answer import AIAnswerErrorCode, AIAnswerRequest
from app.schemas.document_api import (
    KnowledgeCitation,
    KnowledgeResult,
    SearchResponse,
)
from app.services.ai_answer_service import AIAnswerError, AIAnswerService
from app.services.knowledge_service import KnowledgeFilterError
from app.services.llm_provider import (
    GenerationChunk,
    GenerationResult,
    ProviderCapabilities,
)


def evidence(score=0.9, text="Install the signed vManager package.") -> KnowledgeResult:
    return KnowledgeResult(
        knowledge_id=f"document:{uuid4()}",
        text=text,
        score=score,
        document_id=uuid4(),
        version_id=uuid4(),
        chunk_id=uuid4(),
        title="vManager Installation and Configuration",
        citation=KnowledgeCitation(section_title="Installation"),
        metadata={},
    )


class FakeKnowledge:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, tenant_id, request):
        self.calls.append((tenant_id, request))
        if self.error:
            raise self.error
        return SearchResponse(results=self.results)


class FakeProvider:
    name = "fake"
    model = "fake-model"
    capabilities = ProviderCapabilities(True, True, True)

    def __init__(self, outputs=None, stream_output=None):
        self.outputs = list(outputs or ["Answer [C1]"])
        self.stream_output = stream_output or self.outputs[0]
        self.generate_calls = 0
        self.stream_cancelled = False

    async def generate(self, messages, **kwargs):
        value = self.outputs[min(self.generate_calls, len(self.outputs) - 1)]
        self.generate_calls += 1
        return GenerationResult(value, self.model)

    async def stream(self, messages, **kwargs):
        try:
            yield GenerationChunk(self.stream_output)
        finally:
            self.stream_cancelled = True

    async def embed(self, inputs, **kwargs):
        raise AssertionError("AI Answer Service must retrieve only through Knowledge Service")


def config(**values):
    return Settings(
        debug=False,
        environment="test",
        peka_chat_provider="fake",
        peka_ai_min_retrieval_score=values.get("score", 0.5),
        peka_ai_min_evidence_results=values.get("minimum", 1),
        peka_chat_context_window=4096,
        peka_chat_max_output_tokens=512,
    )


def test_zero_and_low_score_results_do_not_call_model():
    for results in ([], [evidence(score=0.1)]):
        provider = FakeProvider()
        service = AIAnswerService(FakeKnowledge(results), provider, config())
        response = asyncio.run(
            service.answer(uuid4(), uuid4(), AIAnswerRequest(query="Unknown?"), "req")
        )
        assert response.grounded is False
        assert response.code == AIAnswerErrorCode.INSUFFICIENT_EVIDENCE
        assert response.citations == []
        assert provider.generate_calls == 0


def test_grounded_answer_calls_knowledge_with_authenticated_tenant():
    tenant_id = uuid4()
    knowledge = FakeKnowledge([evidence()])
    response = asyncio.run(
        AIAnswerService(knowledge, FakeProvider(), config()).answer(
            tenant_id, uuid4(), AIAnswerRequest(query="How?"), "req"
        )
    )
    assert response.grounded is True
    assert response.citations[0].citation_id == "C1"
    assert knowledge.calls[0][0] == tenant_id


def test_missing_citation_retries_once():
    provider = FakeProvider(outputs=["Install the package.", "Install the package. [C1]"])
    response = asyncio.run(
        AIAnswerService(FakeKnowledge([evidence()]), provider, config()).answer(
            uuid4(), uuid4(), AIAnswerRequest(query="How?"), "req"
        )
    )
    assert response.grounded is True
    assert provider.generate_calls == 2


def test_unknown_citation_is_rejected():
    service = AIAnswerService(
        FakeKnowledge([evidence()]), FakeProvider(outputs=["Answer [C99]"]), config()
    )
    with pytest.raises(AIAnswerError) as caught:
        asyncio.run(
            service.answer(uuid4(), uuid4(), AIAnswerRequest(query="How?"), "req")
        )
    assert caught.value.code == AIAnswerErrorCode.CITATION_VALIDATION_FAILED


def test_filter_validation_maps_safely():
    service = AIAnswerService(
        FakeKnowledge(error=KnowledgeFilterError("private tenant detail")),
        FakeProvider(),
        config(),
    )
    with pytest.raises(AIAnswerError) as caught:
        asyncio.run(
            service.answer(uuid4(), uuid4(), AIAnswerRequest(query="How?"), "req")
        )
    assert caught.value.code == AIAnswerErrorCode.INVALID_FILTER
    assert "private" not in caught.value.message


def test_stream_suppresses_reasoning_and_emits_citations_after_tokens():
    provider = FakeProvider(stream_output="<think>hidden chain</think>Final answer. [C1]")
    service = AIAnswerService(FakeKnowledge([evidence()]), provider, config())

    async def collect():
        return [
            item
            async for item in service.stream_answer(
                uuid4(), uuid4(), AIAnswerRequest(query="How?"), "req"
            )
        ]

    events = asyncio.run(collect())
    assert [event["event"] for event in events] == [
        "retrieval", "token", "citations", "complete"
    ]
    assert "hidden chain" not in str(events)
    assert events[1]["data"]["text"] == "Final answer. [C1]"


def test_answer_service_has_no_qdrant_dependency():
    import inspect
    from app.services import ai_answer_service

    source = inspect.getsource(ai_answer_service)
    assert "Qdrant" not in source
    assert "vector_store" not in source


def test_stream_cancellation_reaches_provider():
    class BlockingProvider(FakeProvider):
        async def stream(self, messages, **kwargs):
            try:
                while True:
                    await asyncio.sleep(10)
                    yield GenerationChunk("never")
            finally:
                self.stream_cancelled = True

    provider = BlockingProvider()
    service = AIAnswerService(FakeKnowledge([evidence()]), provider, config())

    async def cancel():
        stream = service.stream_answer(
            uuid4(), uuid4(), AIAnswerRequest(query="How?"), "req"
        )
        assert (await stream.__anext__())["event"] == "retrieval"
        pending = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()

    asyncio.run(cancel())
    assert provider.stream_cancelled is True


def test_observability_does_not_log_query_evidence_or_answer(caplog):
    query = "private-query-marker"
    evidence_text = "private-evidence-marker"
    answer_text = "private-answer-marker [C1]"
    service = AIAnswerService(
        FakeKnowledge([evidence(text=evidence_text)]),
        FakeProvider(outputs=[answer_text]),
        config(),
    )
    with caplog.at_level("INFO"):
        response = asyncio.run(
            service.answer(
                uuid4(), uuid4(), AIAnswerRequest(query=query), "safe-request-id"
            )
        )
    assert response.grounded is True
    logs = caplog.text
    assert "safe-request-id" in logs
    assert query not in logs
    assert evidence_text not in logs
    assert answer_text not in logs


def test_secrets_are_redacted_from_prompt_answer_and_citation_snapshot(caplog):
    class CapturingProvider(FakeProvider):
        def __init__(self):
            super().__init__(
                stream_output="Use password=answer-secret for setup. [C1]"
            )
            self.messages = None

        async def stream(self, messages, **kwargs):
            self.messages = messages
            async for chunk in super().stream(messages, **kwargs):
                yield chunk

    provider = CapturingProvider()
    service = AIAnswerService(
        FakeKnowledge([evidence(text="password=evidence-secret Install it.")]),
        provider,
        config(),
    )

    async def collect():
        return [
            item async for item in service.stream_answer(
                uuid4(), uuid4(), AIAnswerRequest(query="password=user-secret How?"),
                "safe-request",
            )
        ]

    with caplog.at_level("INFO"):
        events = asyncio.run(collect())
    payload = str(events)
    prompt = str(provider.messages)
    assert "user-secret" not in prompt
    assert "evidence-secret" not in prompt
    assert "answer-secret" not in payload
    assert "[REDACTED PASSWORD]" in payload
    citations = next(
        item["data"]["citations"] for item in events if item["event"] == "citations"
    )
    assert citations[0]["sensitive_content_redacted"] is True
    assert "evidence-secret" not in citations[0]["excerpt"]
    assert "evidence-secret" not in caplog.text
