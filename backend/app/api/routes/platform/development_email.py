from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_platform_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.platform_admin import PlatformAdmin
from app.models.tenant import Tenant
from app.models.tenant_user import DevelopmentEmail
from app.schemas.development_email import DevelopmentEmailResponse


router = APIRouter(prefix="/platform/development-email-outbox")


def _ensure_development() -> None:
    if settings.environment.lower() not in {"dev", "local", "development", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


@router.get("", response_model=list[DevelopmentEmailResponse])
def list_development_email(
    tenant_slug: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _admin: PlatformAdmin = Depends(require_platform_admin),
) -> list[DevelopmentEmailResponse]:
    _ensure_development()
    statement = (
        select(DevelopmentEmail, Tenant)
        .join(Tenant, Tenant.id == DevelopmentEmail.tenant_id)
        .order_by(DevelopmentEmail.created_at.desc())
        .limit(200)
    )
    if tenant_slug:
        statement = statement.where(Tenant.slug == tenant_slug)
    return [
        DevelopmentEmailResponse(
            id=email.id,
            tenant_id=email.tenant_id,
            tenant_slug=tenant.slug,
            tenant_name=tenant.display_name,
            recipient=email.recipient,
            subject=email.subject,
            body_text=email.body_text,
            action_url=email.action_url,
            delivery_state=email.delivery_state,
            created_at=email.created_at,
        )
        for email, tenant in db.execute(statement).all()
    ]
