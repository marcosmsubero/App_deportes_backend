from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user

from app.models.meetup import Meetup
from app.models.meetup_participant import MeetupParticipant
from app.models.group import Group
from app.models.user import User

router = APIRouter(prefix="/meetups", tags=["meetups"])


@router.get("/upcoming")
def get_upcoming_meetups(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ✅ Próximas quedadas a las que el usuario SE HA UNIDO (MeetupParticipant).
    No depende de ser miembro del grupo: depende de estar apuntado a la quedada.
    status permitido: open/full (excluye cancelled/done)
    """
    now = datetime.utcnow()
    allowed_status = ("open", "full")

    stmt = (
        select(
            Meetup.id,
            Meetup.starts_at,
            Meetup.meeting_point,
            Meetup.notes,
            Meetup.capacity,
            Meetup.status,
            Group.id.label("group_id"),
            Group.name.label("group_name"),
        )
        .join(MeetupParticipant, MeetupParticipant.meetup_id == Meetup.id)
        .join(Group, Group.id == Meetup.group_id)
        .where(MeetupParticipant.user_id == user.id)
        .where(Meetup.starts_at >= now)
        .where(Meetup.status.in_(allowed_status))
        .order_by(Meetup.starts_at.asc())
        .limit(limit)
    )

    rows = db.execute(stmt).all()

    return [
        {
            "id": r.id,
            "starts_at": r.starts_at,
            "meeting_point": r.meeting_point,
            "notes": r.notes,
            "capacity": r.capacity,
            "status": r.status,
            "group": {"id": r.group_id, "name": r.group_name},
        }
        for r in rows
    ]
