from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PlatformTokenPayload(BaseModel):
    sub: UUID
    username: str
    type: str
    exp: datetime
