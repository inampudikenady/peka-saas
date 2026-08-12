from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DevelopmentEmailResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    recipient: str
    subject: str
    body_text: str
    action_url: str
    delivery_state: str
    created_at: datetime
