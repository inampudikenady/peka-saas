"""Private, owner-scoped tenant AI conversation APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.auth import allow_tenant_user
from app.api.dependencies import get_ai_conversation_service
from app.api.tenant_context import get_current_tenant_context
from app.core.tenant_context import TenantContext
from app.models.tenant_user import TenantUser
from app.schemas.ai_conversation import (
    ConversationArchive,
    ConversationCreate,
    ConversationDetail,
    ConversationList,
    ConversationRename,
    CitationEvidence,
)
from app.services.ai_conversation_service import (
    AIConversationService,
    ConversationNotFoundError,
)


router = APIRouter(prefix="/tenant/ai/conversations")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Conversation not found.")


@router.post("", response_model=ConversationDetail, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    return service.create(tenant.tenant_id, user.id, payload.title)


@router.get("", response_model=ConversationList)
def list_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    archived: bool | None = None,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    return service.list(
        tenant.tenant_id, user.id, limit=limit, offset=offset, archived=archived
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
def conversation_detail(
    conversation_id: UUID,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    try:
        return service.detail(tenant.tenant_id, user.id, conversation_id)
    except ConversationNotFoundError:
        raise _not_found()


@router.patch("/{conversation_id}/title", response_model=ConversationDetail)
def rename_conversation(
    conversation_id: UUID,
    payload: ConversationRename,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    try:
        return service.rename(tenant.tenant_id, user.id, conversation_id, payload.title)
    except ConversationNotFoundError:
        raise _not_found()


@router.patch("/{conversation_id}/archive", response_model=ConversationDetail)
def archive_conversation(
    conversation_id: UUID,
    payload: ConversationArchive,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    try:
        return service.archive(
            tenant.tenant_id, user.id, conversation_id, payload.is_archived
        )
    except ConversationNotFoundError:
        raise _not_found()


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    try:
        service.delete(tenant.tenant_id, user.id, conversation_id)
    except ConversationNotFoundError:
        raise _not_found()
    return Response(status_code=204)


@router.get(
    "/{conversation_id}/messages/{message_id}/citations/{citation_id}",
    response_model=CitationEvidence,
)
def citation_evidence(
    conversation_id: UUID,
    message_id: UUID,
    citation_id: str,
    tenant: TenantContext = Depends(get_current_tenant_context),
    user: TenantUser = Depends(allow_tenant_user),
    service: AIConversationService = Depends(get_ai_conversation_service),
):
    try:
        return service.citation_evidence(
            tenant.tenant_id, user.id, conversation_id, message_id, citation_id
        )
    except ConversationNotFoundError:
        raise _not_found()
