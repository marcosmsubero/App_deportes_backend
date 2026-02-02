from pydantic import BaseModel
from typing import Optional

class GroupCreate(BaseModel):
    name: str
    sport: str
    city: str
    is_private: bool = False

class GroupPublic(BaseModel):
    id: int
    name: str
    sport: str
    city: str
    is_private: bool
    owner_id: int

    members_count: Optional[int] = None
    my_role: Optional[str] = None