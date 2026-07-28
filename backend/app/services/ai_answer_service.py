"""Stateless, tenant-grounded answer orchestration through Knowledge Service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

from app.core.config import Settings, settings
from app.schemas.ai_answer import (
    AIAnswerErrorCode,
    AIAnswerCitation,
    AIAnswerRequest,
    AIAnswerResponse,
    AIModelSummary,
    AIRetrievalSummary,
)
from app.schemas.document_api import SearchRequest
from app.services.citation_validator import (
    CitationValidationError,
    normalize_answer,
    validate_citations,
)
from app.services.knowledge_service import KnowledgeFilterError, KnowledgeService
from app.services.llm_provider import (
    GenerationResult,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
)
from app.services.prompt_builder import (
    PromptBuildResult,
    PromptBuilder,
    PromptContextExceeded,
)
from app.services.secret_redaction import SecretRedactionService


logger = logging.getLogger(__name__)
INSUFFICIENT_MESSAGE = (
    "I could not find enough information in the available PEKA knowledge sources "
    "to answer that question."
)


class AIAnswerError(RuntimeError):
    def __init__(self, code: AIAnswerErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _PreparedAnswer:
    prompt: PromptBuildResult | None
    retrieval: AIRetrievalSummary


class AIAnswerService:
    def __init__(
        self,
        knowledge: KnowledgeService,
        provider: LLMProvider,
        config: Settings = settings,
    ) -> None:
        self.knowledge = knowledge
        self.provider = provider
        self.config = config
        self.redactor = SecretRedactionService(
            enabled=config.peka_ai_secret_detection_enabled
        )
        self.prompt_builder = PromptBuilder(
            context_window=config.peka_chat_context_window,
            output_token_reservation=config.peka_chat_max_output_tokens,
            max_evidence_characters_per_chunk=(
                config.peka_ai_max_evidence_characters_per_chunk
            ),
            max_evidence_tokens=config.peka_ai_max_evidence_tokens,
            max_total_prompt_tokens=config.peka_ai_max_total_prompt_tokens,
        )

    def _validate_request(self, request: AIAnswerRequest) -> tuple[str, int]:
        query = request.query.strip()
        if not query:
            raise AIAnswerError(
                AIAnswerErrorCode.INVALID_QUERY, "A non-empty question is required."
            )
        if len(query) > self.config.peka_ai_max_query_characters:
            raise AIAnswerError(
                AIAnswerErrorCode.QUERY_TOO_LONG,
                "The question exceeds the permitted length.",
            )
        top_k = request.top_k or self.config.peka_ai_default_top_k
        if top_k > self.config.peka_ai_max_top_k:
            raise AIAnswerError(
                AIAnswerErrorCode.INVALID_QUERY,
                "The requested result count exceeds the permitted maximum.",
            )
        return query, top_k

    def _prepare(
        self,
        tenant_id: UUID,
        request: AIAnswerRequest,
        conversation_context: str = "",
    ) -> _PreparedAnswer:
        query, top_k = self._validate_request(request)
        query = self.redactor.redact(query).text
        conversation_context = self.redactor.redact(conversation_context).text
        started = monotonic()
        try:
            response = self.knowledge.search(
                tenant_id,
                SearchRequest(query=query, top_k=top_k, filters=request.filters),
            )
        except KnowledgeFilterError as exc:
            raise AIAnswerError(
                AIAnswerErrorCode.INVALID_FILTER,
                "One or more knowledge filters are not available for this tenant.",
            ) from exc
        except Exception as exc:
            raise AIAnswerError(
                AIAnswerErrorCode.KNOWLEDGE_UNAVAILABLE,
                "Tenant knowledge retrieval is temporarily unavailable.",
            ) from exc
        safe_results = []
        for result in response.results:
            redaction = self.redactor.redact(result.text)
            metadata = dict(result.metadata)
            metadata["sensitive_content_redacted"] = redaction.redacted
            metadata["redaction_categories"] = list(redaction.detections)
            safe_results.append(result.model_copy(update={
                "text": redaction.text,
                "metadata": metadata,
            }))
            if redaction.redacted:
                logger.warning(
                    "AI evidence secrets redacted tenant_id=%s document_id=%s "
                    "chunk_id=%s categories=%s count=%s",
                    tenant_id, result.document_id, result.chunk_id,
                    ",".join(sorted(redaction.detections)),
                    sum(redaction.detections.values()),
                )
        eligible = [
            result
            for result in safe_results
            if result.score >= self.config.peka_ai_min_retrieval_score
            and result.document_id
            and result.version_id
            and result.chunk_id
            and result.title
        ]
        retrieval = AIRetrievalSummary(
            result_count=len(response.results),
            included_count=0,
            top_k=top_k,
        )
        if len(eligible) < self.config.peka_ai_min_evidence_results:
            logger.info(
                "AI evidence insufficient tenant_id=%s result_count=%s eligible_count=%s "
                "duration_ms=%s",
                tenant_id,
                len(response.results),
                len(eligible),
                round((monotonic() - started) * 1000),
            )
            return _PreparedAnswer(prompt=None, retrieval=retrieval)
        try:
            prompt = self.prompt_builder.build(
                query, eligible, conversation_context=conversation_context
            )
        except PromptContextExceeded as exc:
            raise AIAnswerError(
                AIAnswerErrorCode.CONTEXT_LIMIT_EXCEEDED,
                "The retrieved evidence exceeds the configured context limit.",
            ) from exc
        retrieval.included_count = len(prompt.citation_map)
        logger.info(
            "AI prompt built tenant_id=%s result_count=%s included_count=%s "
            "estimated_tokens=%s prompt_version=%s duration_ms=%s",
            tenant_id,
            len(response.results),
            retrieval.included_count,
            prompt.estimated_token_count,
            prompt.prompt_version,
            round((monotonic() - started) * 1000),
        )
        return _PreparedAnswer(prompt=prompt, retrieval=retrieval)

    @staticmethod
    def _provider_error(exc: LLMProviderError) -> AIAnswerError:
        try:
            code = AIAnswerErrorCode(exc.code)
        except ValueError:
            code = AIAnswerErrorCode.AI_GENERATION_FAILED
        messages = {
            AIAnswerErrorCode.CHAT_PROVIDER_NOT_CONFIGURED:
                "The AI service is not configured.",
            AIAnswerErrorCode.CHAT_PROVIDER_UNAVAILABLE:
                "The AI service is temporarily unavailable.",
            AIAnswerErrorCode.CHAT_PROVIDER_TIMEOUT:
                "The AI service did not respond in time.",
            AIAnswerErrorCode.CHAT_PROVIDER_RATE_LIMITED:
                "The AI service is temporarily busy. Please try again.",
            AIAnswerErrorCode.CHAT_PROVIDER_INVALID_RESPONSE:
                "The AI service returned an invalid response.",
            AIAnswerErrorCode.CONTEXT_LIMIT_EXCEEDED:
                "The evidence exceeds the configured model context.",
        }
        return AIAnswerError(
            code, messages.get(code, "The AI service could not generate an answer.")
        )

    async def _generate_validated(
        self, prompt: PromptBuildResult, initial: GenerationResult | None = None
    ) -> tuple[str, list[AIAnswerCitation], str]:
        result = initial
        for attempt in range(2):
            if result is None:
                messages = list(prompt.messages)
                if attempt == 1:
                    messages.append(
                        LLMMessage(
                            role="user",
                            content=(
                                "Regenerate the final answer. Every factual claim must include "
                                "at least one supplied citation such as [C1]. Return only the "
                                "final cited answer."
                            ),
                        )
                    )
                try:
                    result = await self.provider.generate(
                        messages,
                        temperature=self.config.peka_chat_temperature,
                        max_output_tokens=self.config.peka_chat_max_output_tokens,
                    )
                except LLMProviderError as exc:
                    raise self._provider_error(exc) from exc
            answer = self.redactor.redact(normalize_answer(result.text)).text
            try:
                citations = validate_citations(answer, prompt.citation_map)
            except CitationValidationError as exc:
                raise AIAnswerError(
                    AIAnswerErrorCode.CITATION_VALIDATION_FAILED,
                    "The generated answer did not contain valid citations.",
                ) from exc
            if answer and citations:
                return answer, citations, result.model
            result = None
        raise AIAnswerError(
            AIAnswerErrorCode.CITATION_VALIDATION_FAILED,
            "The generated answer did not contain valid citations.",
        )

    def _insufficient(
        self, retrieval: AIRetrievalSummary, request_id: str
    ) -> AIAnswerResponse:
        return AIAnswerResponse(
            answer=INSUFFICIENT_MESSAGE,
            grounded=False,
            code=AIAnswerErrorCode.INSUFFICIENT_EVIDENCE,
            citations=[],
            retrieval=retrieval,
            model=None,
            request_id=request_id,
        )

    async def answer(
        self,
        tenant_id: UUID,
        user_id: UUID,
        request: AIAnswerRequest,
        request_id: str,
        conversation_context: str = "",
    ) -> AIAnswerResponse:
        logger.info(
            "AI answer request received tenant_id=%s user_id=%s request_id=%s",
            tenant_id,
            user_id,
            request_id,
        )
        prepared = self._prepare(tenant_id, request, conversation_context)
        if prepared.prompt is None:
            return self._insufficient(prepared.retrieval, request_id)
        answer, citations, model = await self._generate_validated(prepared.prompt)
        return AIAnswerResponse(
            answer=answer,
            grounded=True,
            citations=citations,
            retrieval=prepared.retrieval,
            model=AIModelSummary(provider=self.provider.name, model=model),
            request_id=request_id,
        )

    async def stream_answer(
        self,
        tenant_id: UUID,
        user_id: UUID,
        request: AIAnswerRequest,
        request_id: str,
        conversation_context: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        logger.info(
            "AI answer stream started tenant_id=%s user_id=%s request_id=%s",
            tenant_id,
            user_id,
            request_id,
        )
        try:
            prepared = self._prepare(tenant_id, request, conversation_context)
            yield {
                "event": "retrieval",
                "data": prepared.retrieval.model_dump(mode="json"),
            }
            if prepared.prompt is None:
                yield {"event": "token", "data": {"text": INSUFFICIENT_MESSAGE}}
                yield {"event": "citations", "data": {"citations": []}}
                yield {
                    "event": "complete",
                    "data": {
                        "grounded": False,
                        "code": AIAnswerErrorCode.INSUFFICIENT_EVIDENCE.value,
                        "request_id": request_id,
                    },
                }
                return
            streamed = ""
            try:
                async for chunk in self.provider.stream(
                    prepared.prompt.messages,
                    temperature=self.config.peka_chat_temperature,
                    max_output_tokens=self.config.peka_chat_max_output_tokens,
                ):
                    streamed += chunk.text
            except LLMProviderError as exc:
                raise self._provider_error(exc) from exc
            initial = GenerationResult(text=streamed, model=self.provider.model)
            answer, citations, model = await self._generate_validated(
                prepared.prompt, initial
            )
            # Buffering until citation validation prevents invalid or reasoning
            # content from reaching the transport. Emit bounded final deltas.
            for start in range(0, len(answer), 96):
                yield {"event": "token", "data": {"text": answer[start:start + 96]}}
                await asyncio.sleep(0)
            yield {
                "event": "citations",
                "data": {
                    "citations": [
                        citation.model_dump(mode="json") for citation in citations
                    ]
                },
            }
            yield {
                "event": "complete",
                "data": {
                    "grounded": True,
                    "request_id": request_id,
                    "model": {
                        "provider": self.provider.name,
                        "model": model,
                    },
                    "prompt_version": prepared.prompt.prompt_version,
                },
            }
        except asyncio.CancelledError:
            logger.info(
                "AI answer generation task cancelled tenant_id=%s user_id=%s "
                "request_id=%s",
                tenant_id,
                user_id,
                request_id,
            )
            raise
