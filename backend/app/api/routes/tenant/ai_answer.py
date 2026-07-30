"""Authenticated tenant transports for grounded conversation answers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_ai_conversation_service, get_knowledge_service
from app.api.auth import allow_tenant_user
from app.api.tenant_context import get_current_tenant_context
from app.core.logging import request_id_ctx
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.tenant_user import TenantUser
from app.models.ai_conversation import AIMessageStatus
from app.schemas.ai_answer import (
    AIAnswerErrorCode,
    AIAnswerErrorResponse,
    AIAnswerRequest,
    AIAnswerResponse,
    AIPromptSuggestionsResponse,
)
from app.repositories.document_repository import DocumentRepository
from app.services.ai_answer_service import AIAnswerError, AIAnswerService
from app.services.assistant_operational import (
    OperationalAssistantService,
    classify_assistant_intent,
)
from app.services.knowledge_service import KnowledgeService
from app.services.ai_conversation_service import (
    AIConversationService,
    ConversationGenerationInProgressError,
    ConversationNotFoundError,
)
from app.services.provider_factory import chat_provider
from app.services.prompt_builder import PROMPT_VERSION


router = APIRouter(prefix="/tenant/ai")
logger = logging.getLogger(__name__)
SSE_KEEPALIVE_SECONDS = 10.0


@router.get("/suggestions", response_model=AIPromptSuggestionsResponse)
def prompt_suggestions(
    tenant: TenantContext = Depends(get_current_tenant_context),
    _user: TenantUser = Depends(allow_tenant_user),
    db: Session = Depends(get_db),
) -> AIPromptSuggestionsResponse:
    filenames = DocumentRepository(db).list_indexed_document_titles(
        tenant.tenant_id,
    )
    if not filenames:
        return AIPromptSuggestionsResponse(
            has_indexed_knowledge=False,
            onboarding_guidance=(
                "Index tenant documents or connect a knowledge source before "
                "asking PEKA organization-specific questions."
            ),
        )
    suggestions = []
    for index, filename in enumerate(filenames):
        title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
        if index == 0:
            suggestions.append(f"Summarize {title}.")
        elif index == 1:
            suggestions.append(f"What are the key procedures in {title}?")
        else:
            suggestions.append(f"What should I know about {title}?")
    return AIPromptSuggestionsResponse(
        has_indexed_knowledge=True,
        suggestions=suggestions,
    )


def get_ai_answer_service(
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> AIAnswerService:
    return AIAnswerService(knowledge, chat_provider())


def _status_for(code: AIAnswerErrorCode) -> int:
    return {
        AIAnswerErrorCode.INVALID_QUERY: 422,
        AIAnswerErrorCode.QUERY_TOO_LONG: 422,
        AIAnswerErrorCode.INVALID_FILTER: 422,
        AIAnswerErrorCode.KNOWLEDGE_UNAVAILABLE: 503,
        AIAnswerErrorCode.CHAT_PROVIDER_NOT_CONFIGURED: 503,
        AIAnswerErrorCode.CHAT_PROVIDER_UNAVAILABLE: 503,
        AIAnswerErrorCode.CHAT_PROVIDER_TIMEOUT: 504,
        AIAnswerErrorCode.CHAT_PROVIDER_RATE_LIMITED: 429,
        AIAnswerErrorCode.CHAT_PROVIDER_INVALID_RESPONSE: 502,
        AIAnswerErrorCode.CONTEXT_LIMIT_EXCEEDED: 422,
        AIAnswerErrorCode.CITATION_VALIDATION_FAILED: 502,
        AIAnswerErrorCode.AI_GENERATION_FAILED: 502,
        AIAnswerErrorCode.INSUFFICIENT_EVIDENCE: 200,
    }[code]


def ai_error_response(exc: AIAnswerError, request_id: str) -> JSONResponse:
    body = AIAnswerErrorResponse(
        code=exc.code, message=exc.message, request_id=request_id
    )
    return JSONResponse(
        status_code=_status_for(exc.code),
        content=body.model_dump(mode="json"),
    )


@router.post(
    "/answer",
    response_model=AIAnswerResponse,
    responses={
        422: {"model": AIAnswerErrorResponse},
        429: {"model": AIAnswerErrorResponse},
        502: {"model": AIAnswerErrorResponse},
        503: {"model": AIAnswerErrorResponse},
        504: {"model": AIAnswerErrorResponse},
    },
)
async def answer(
    payload: AIAnswerRequest,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIAnswerService = Depends(get_ai_answer_service),
    conversation_service: AIConversationService = Depends(
        get_ai_conversation_service
    ),
    db: Session = Depends(get_db),
) -> AIAnswerResponse | JSONResponse:
    request_id = request_id_ctx.get()
    try:
        conversation_context = (
            conversation_service.generation_context(
                tenant.tenant_id, user.id, payload.conversation_id
            )
            if payload.conversation_id else None
        )
        _conversation, assistant_message = conversation_service.begin_message(
            tenant.tenant_id,
            user.id,
            payload.query,
            payload.conversation_id,
            context_message_ids=(
                conversation_context.message_ids if conversation_context else []
            ),
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ConversationGenerationInProgressError:
        raise HTTPException(
            status_code=409,
            detail="A response is already being generated for this conversation.",
        )
    try:
        intent = classify_assistant_intent(payload.query)
        if intent.destination != "document":
            operational = await OperationalAssistantService(db).answer(
                tenant.tenant_id, user.id, intent
            )
            response = AIAnswerResponse(
                answer=operational.text,
                grounded=True,
                citations=[],
                retrieval={
                    "result_count": 1 if operational.result is not None else 0,
                    "included_count": 1 if operational.result is not None else 0,
                    "top_k": 1,
                },
                model=None,
                request_id=request_id,
            )
        else:
            response = await service.answer(
                tenant.tenant_id,
                user.id,
                payload,
                request_id,
                conversation_context=conversation_context.text if conversation_context else "",
            )
        conversation_service.complete(
            tenant.tenant_id,
            user.id,
            assistant_message.id,
            content=response.answer,
            citations=[
                citation.model_dump(mode="json") for citation in response.citations
            ],
            retrieval=response.retrieval.model_dump(mode="json"),
            model=response.model.model if response.model else None,
            prompt_version=(
                "operational-tools-v1"
                if intent.destination != "document"
                else PROMPT_VERSION if response.grounded else None
            ),
        )
        return response
    except AIAnswerError as exc:
        conversation_service.terminate(
            tenant.tenant_id,
            user.id,
            assistant_message.id,
            status=AIMessageStatus.FAILED,
            partial_content="",
            code=exc.code.value,
        )
        logger.warning(
            "AI answer failed tenant_id=%s user_id=%s request_id=%s error_code=%s",
            tenant.tenant_id,
            user.id,
            request_id,
            exc.code.value,
        )
        return ai_error_response(exc, request_id)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.post("/answer/stream")
async def stream_answer(
    payload: AIAnswerRequest,
    request: Request,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIAnswerService = Depends(get_ai_answer_service),
    conversation_service: AIConversationService = Depends(
        get_ai_conversation_service
    ),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    request_id = request_id_ctx.get()
    try:
        conversation_context = (
            conversation_service.generation_context(
                tenant.tenant_id, user.id, payload.conversation_id
            )
            if payload.conversation_id else None
        )
        conversation, assistant_message = conversation_service.begin_message(
            tenant.tenant_id,
            user.id,
            payload.query,
            payload.conversation_id,
            context_message_ids=(
                conversation_context.message_ids if conversation_context else []
            ),
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ConversationGenerationInProgressError:
        raise HTTPException(
            status_code=409,
            detail="A response is already being generated for this conversation.",
        )

    intent = classify_assistant_intent(payload.query)

    async def operational_stream() -> AsyncGenerator[dict[str, Any], None]:
        answer = await OperationalAssistantService(db).answer(
            tenant.tenant_id, user.id, intent
        )
        included = 1 if answer.result is not None else 0
        yield {
            "event": "retrieval",
            "data": {
                "result_count": included,
                "included_count": included,
                "top_k": 1,
                "source": "connector",
                "tool_name": answer.tool_name,
                "tool_request_id": (
                    str(answer.tool_request_id) if answer.tool_request_id else None
                ),
            },
        }
        for start in range(0, len(answer.text), 96):
            yield {"event": "token", "data": {"text": answer.text[start:start + 96]}}
            await asyncio.sleep(0)
        yield {"event": "citations", "data": {"citations": []}}
        yield {
            "event": "complete",
            "data": {
                "grounded": True,
                "request_id": request_id,
                "prompt_version": "operational-tools-v1",
            },
        }

    async def events() -> AsyncGenerator[str, None]:
        stream = (
            operational_stream()
            if intent.destination != "document"
            else service.stream_answer(
                tenant.tenant_id,
                user.id,
                payload,
                request_id,
                conversation_context=(
                    conversation_context.text if conversation_context else ""
                ),
            )
        )
        queue: asyncio.Queue[dict[str, Any] | BaseException | None] = asyncio.Queue()
        event_count = 0
        byte_count = 0
        last_event = "none"
        completed = False
        persisted_terminal = False
        assistant_text = ""
        citations: list[dict[str, Any]] = []
        retrieval: dict[str, Any] = {}

        async def produce() -> None:
            try:
                async for item in stream:
                    await queue.put(item)
            except BaseException as exc:
                await queue.put(exc)
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())

        def frame(event: str, data: dict[str, Any]) -> str:
            nonlocal event_count, byte_count, last_event
            value = _sse(event, data)
            event_count += 1
            byte_count += len(value.encode("utf-8"))
            last_event = event
            return value

        try:
            yield frame(
                "status",
                {
                    "status": "started",
                    "request_id": request_id,
                    "conversation_id": str(conversation.id),
                    "assistant_message_id": str(assistant_message.id),
                },
            )
            while True:
                if await request.is_disconnected():
                    conversation_service.terminate(
                        tenant.tenant_id,
                        user.id,
                        assistant_message.id,
                        status=AIMessageStatus.CANCELLED,
                        partial_content=assistant_text,
                        code="CLIENT_DISCONNECTED",
                    )
                    persisted_terminal = True
                    logger.info(
                        "AI answer stream client disconnected tenant_id=%s user_id=%s "
                        "request_id=%s events_sent=%s bytes_sent=%s last_event=%s "
                        "is_disconnected=true",
                        tenant.tenant_id, user.id, request_id, event_count, byte_count,
                        last_event,
                    )
                    break
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=SSE_KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    keepalive = ": keepalive\n\n"
                    event_count += 1
                    byte_count += len(keepalive.encode("utf-8"))
                    last_event = "keepalive"
                    yield keepalive
                    continue
                if item is None:
                    if not completed:
                        raise RuntimeError("AI answer stream ended without a terminal event")
                    break
                if isinstance(item, AIAnswerError):
                    conversation_service.terminate(
                        tenant.tenant_id,
                        user.id,
                        assistant_message.id,
                        status=AIMessageStatus.FAILED,
                        partial_content=assistant_text,
                        code=item.code.value,
                    )
                    persisted_terminal = True
                    logger.warning(
                        "AI answer stream failed tenant_id=%s user_id=%s request_id=%s "
                        "error_code=%s",
                        tenant.tenant_id, user.id, request_id, item.code.value,
                    )
                    yield frame(
                        "error",
                        {
                            "code": item.code.value,
                            "message": item.message,
                            "request_id": request_id,
                        },
                    )
                    break
                if isinstance(item, BaseException):
                    raise item
                event = item["event"]
                if event == "token":
                    assistant_text += str(item["data"].get("text") or "")
                elif event == "citations":
                    citations = list(item["data"].get("citations") or [])
                elif event == "retrieval":
                    retrieval = dict(item["data"])
                elif event == "complete":
                    model_data = item["data"].get("model") or {}
                    conversation_service.complete(
                        tenant.tenant_id,
                        user.id,
                        assistant_message.id,
                        content=assistant_text,
                        citations=citations,
                        retrieval=retrieval,
                        model=model_data.get("model"),
                        prompt_version=item["data"].get("prompt_version"),
                    )
                    persisted_terminal = True
                yield frame(event, item["data"])
                if event == "complete":
                    completed = True
            if completed:
                logger.info(
                    "AI answer stream completed tenant_id=%s user_id=%s request_id=%s "
                    "events_sent=%s bytes_sent=%s last_event=%s is_disconnected=false",
                    tenant.tenant_id, user.id, request_id, event_count, byte_count,
                    last_event,
                )
        except asyncio.CancelledError:
            if not persisted_terminal:
                conversation_service.terminate(
                    tenant.tenant_id,
                    user.id,
                    assistant_message.id,
                    status=AIMessageStatus.CANCELLED,
                    partial_content=assistant_text,
                    code="TRANSPORT_CANCELLED",
                )
                persisted_terminal = True
            disconnected = await request.is_disconnected()
            logger.info(
                "AI answer stream transport cancelled tenant_id=%s user_id=%s "
                "request_id=%s events_sent=%s bytes_sent=%s last_event=%s "
                "is_disconnected=%s",
                tenant.tenant_id, user.id, request_id, event_count, byte_count,
                last_event, str(disconnected).lower(),
            )
            raise
        except Exception:
            if not persisted_terminal:
                conversation_service.terminate(
                    tenant.tenant_id,
                    user.id,
                    assistant_message.id,
                    status=AIMessageStatus.FAILED,
                    partial_content=assistant_text,
                    code="AI_GENERATION_FAILED",
                )
                persisted_terminal = True
            disconnected = await request.is_disconnected()
            logger.exception(
                "AI answer stream unexpected failure tenant_id=%s user_id=%s "
                "request_id=%s events_sent=%s bytes_sent=%s last_event=%s "
                "is_disconnected=%s",
                tenant.tenant_id, user.id, request_id, event_count, byte_count,
                last_event, str(disconnected).lower(),
            )
            if not disconnected:
                yield frame(
                    "error",
                    {
                        "code": AIAnswerErrorCode.AI_GENERATION_FAILED.value,
                        "message": "The AI service could not complete the answer stream.",
                        "request_id": request_id,
                    },
                )
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
            with suppress(RuntimeError):
                await stream.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
