from datetime import datetime
from pydantic import BaseModel

class InviteCreateRequest(BaseModel):
    expires_at: datetime | None = None  # si None, no expira
    max_uses: int | None = None         # si None, usos ilimitados

class InvitePublic(BaseModel):
    token: str
    group_id: int
    expires_at: datetime | None
    is_active: bool
    uses: int
    max_uses: int | None
    revoked_at: datetime | None
