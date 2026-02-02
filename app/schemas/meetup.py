from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from .user import UserPublic  # ajusta si tu import es distinto


class MeetupCreate(BaseModel):
    starts_at: datetime
    meeting_point: str
    notes: Optional[str] = None

    level_tag: Optional[str] = None
    pace_min: Optional[int] = None
    pace_max: Optional[int] = None

    capacity: Optional[int] = None


class MeetupPublic(BaseModel):
    id: int
    group_id: int
    created_by: int
    starts_at: datetime
    meeting_point: str
    notes: Optional[str] = None

    level_tag: Optional[str] = None
    pace_min: Optional[int] = None
    pace_max: Optional[int] = None

    capacity: Optional[int] = None   # 👈 FIX CLAVE

    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class MeetupPublicWithParticipants(MeetupPublic):
    participants: List[UserPublic] = []
