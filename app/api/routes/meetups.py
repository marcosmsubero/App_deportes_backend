from datetime import datetime, timezone

import anyio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.auth import get_current_user, get_current_user_optional
from app.models.group import Group
from app.models.membership import GroupMember
from app.models.meetup import Meetup
from app.models.meetup_participant import MeetupParticipant
from app.models.user import User
from app.schemas.meetup import MeetupCreate, MeetupPublic, MeetupPublicWithParticipants
from app.schemas.user import UserPublic
from app.realtime.sse import broadcast  # ✅ SSE

router = APIRouter(tags=["meetups"])


def _is_member(db: Session, group_id: int, user_id: int) -> bool:
    m = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    return m is not None


def _can_manage_meetup(db: Session, meetup: Meetup, user: User) -> bool:
    if meetup.created_by == user.id:
        return True
    group = db.get(Group, meetup.group_id)
    return group and group.owner_id == user.id


def _to_utc_naive(dt: datetime) -> datetime:
    """
    DB guarda DateTime naive.
    Regla: lo guardamos como UTC naive.
    - Si dt es naive: asumimos que YA está en UTC.
    - Si dt tiene tz: convertimos a UTC y quitamos tzinfo.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_z_from_utc_naive(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/meetups/{meetup_id}")
def get_meetup(
    meetup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meetup = db.get(Meetup, meetup_id)
    if not meetup:
        raise HTTPException(status_code=404, detail="Quedada no encontrada")

    if not _is_member(db, meetup.group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Debes ser miembro del grupo")

    group = db.get(Group, meetup.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    return {
        "id": meetup.id,
        "group_id": meetup.group_id,
        "starts_at": _iso_z_from_utc_naive(meetup.starts_at),
        "meeting_point": meetup.meeting_point,
        "status": meetup.status,
        "group": {
            "id": group.id,
            "name": group.name,
        },
    }


@router.post("/groups/{group_id}/meetups", response_model=MeetupPublic)
def create_meetup(
    group_id: int,
    payload: MeetupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if not _is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Debes ser miembro del grupo")

    starts_at_utc = _to_utc_naive(payload.starts_at)

    meetup = Meetup(
        group_id=group_id,
        created_by=current_user.id,
        starts_at=starts_at_utc,
        meeting_point=payload.meeting_point.strip(),
        notes=(payload.notes.strip() if payload.notes else None),
        level_tag=(payload.level_tag.strip().lower() if payload.level_tag else None),
        pace_min=payload.pace_min,
        pace_max=payload.pace_max,
        capacity=payload.capacity,
        status="open",
    )
    db.add(meetup)
    db.commit()
    db.refresh(meetup)

    # creador entra como participante
    db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user.id))
    db.commit()

    # 🔴 SSE: meetup creado (payload completo -> FRONT SIN GET extra)
    anyio.from_thread.run(
        broadcast,
        "MEETUP_CREATED",
        {
            "id": meetup.id,
            "group_id": meetup.group_id,
            "group_name": group.name,
            "meeting_point": meetup.meeting_point,
            "starts_at": _iso_z_from_utc_naive(meetup.starts_at),
            "status": meetup.status,
        },
    )

    return MeetupPublic(
        id=meetup.id,
        group_id=meetup.group_id,
        created_by=meetup.created_by,
        starts_at=meetup.starts_at,
        meeting_point=meetup.meeting_point,
        notes=meetup.notes,
        level_tag=meetup.level_tag,
        pace_min=meetup.pace_min,
        pace_max=meetup.pace_max,
        capacity=meetup.capacity,
        status=meetup.status,
        created_at=meetup.created_at,
    )


@router.get("/groups/{group_id}/meetups", response_model=list[MeetupPublicWithParticipants])
def list_meetups(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    now_utc = _utc_now_naive()

    stmt = (
        select(Meetup)
        .where(Meetup.group_id == group_id)
        .where(Meetup.status.in_(["open", "full"]))
        .where(Meetup.starts_at >= now_utc)
        .order_by(Meetup.starts_at.asc())
    )
    meetups = db.execute(stmt).scalars().all()

    out: list[MeetupPublicWithParticipants] = []

    for m in meetups:
        p_stmt = (
            select(User)
            .join(MeetupParticipant, MeetupParticipant.user_id == User.id)
            .where(MeetupParticipant.meetup_id == m.id)
        )
        users = db.execute(p_stmt).scalars().all()

        participants = [UserPublic(id=u.id, email=u.email) for u in users]
        participant_ids = {u.id for u in users}

        out.append(
            MeetupPublicWithParticipants(
                id=m.id,
                group_id=m.group_id,
                created_by=m.created_by,
                starts_at=m.starts_at,
                meeting_point=m.meeting_point,
                notes=m.notes,
                level_tag=m.level_tag,
                pace_min=m.pace_min,
                pace_max=m.pace_max,
                capacity=m.capacity,
                status=m.status,
                created_at=m.created_at,
                participants_count=len(participants),
                participants=participants,
                is_joined=(current_user is not None and current_user.id in participant_ids),
            )
        )

    return out


@router.post("/meetups/{meetup_id}/join")
def join_meetup(
    meetup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meetup = db.get(Meetup, meetup_id)
    if not meetup:
        raise HTTPException(status_code=404, detail="Quedada no encontrada")

    if meetup.status == "full":
        raise HTTPException(status_code=409, detail="Quedada completa")
    if meetup.status != "open":
        raise HTTPException(status_code=400, detail="Quedada no abierta")

    if not _is_member(db, meetup.group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Debes ser miembro del grupo")

    existing = db.execute(
        select(MeetupParticipant).where(
            MeetupParticipant.meetup_id == meetup_id,
            MeetupParticipant.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if existing:
        return {"ok": True, "message": "Ya estabas apuntado"}

    if meetup.capacity:
        count = db.execute(
            select(func.count())
            .select_from(MeetupParticipant)
            .where(MeetupParticipant.meetup_id == meetup_id)
        ).scalar_one()
        if count >= meetup.capacity:
            raise HTTPException(status_code=409, detail="Quedada completa")

    db.add(MeetupParticipant(meetup_id=meetup_id, user_id=current_user.id))
    db.commit()

    anyio.from_thread.run(
        broadcast,
        "MEETUP_JOINED",
        {
            "meetup_id": meetup.id,
            "group_id": meetup.group_id,
            "user_id": current_user.id,
        },
    )

    return {"ok": True, "message": "Apuntado a la quedada"}


@router.post("/meetups/{meetup_id}/leave")
def leave_meetup(
    meetup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meetup = db.get(Meetup, meetup_id)
    if not meetup:
        raise HTTPException(status_code=404, detail="Quedada no encontrada")

    participation = db.execute(
        select(MeetupParticipant).where(
            MeetupParticipant.meetup_id == meetup_id,
            MeetupParticipant.user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if not participation:
        return {"ok": True, "message": "No estabas apuntado"}

    db.delete(participation)
    db.commit()

    if meetup.status == "full":
        meetup.status = "open"
        db.commit()

    anyio.from_thread.run(
        broadcast,
        "MEETUP_LEFT",
        {
            "meetup_id": meetup.id,
            "group_id": meetup.group_id,
            "user_id": current_user.id,
            "status": meetup.status,
        },
    )

    return {"ok": True, "message": "Te has desapuntado"}


@router.post("/meetups/{meetup_id}/cancel")
def cancel_meetup(
    meetup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meetup = db.get(Meetup, meetup_id)
    if not meetup:
        raise HTTPException(status_code=404, detail="Quedada no encontrada")

    if not _can_manage_meetup(db, meetup, current_user):
        raise HTTPException(status_code=403, detail="No autorizado")

    meetup.status = "cancelled"
    db.commit()

    anyio.from_thread.run(
        broadcast,
        "MEETUP_CANCELLED",
        {
            "meetup_id": meetup.id,
            "group_id": meetup.group_id,
            "status": meetup.status,
        },
    )

    return {"ok": True, "status": meetup.status}


@router.post("/meetups/{meetup_id}/done")
def done_meetup(
    meetup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meetup = db.get(Meetup, meetup_id)
    if not meetup:
        raise HTTPException(status_code=404, detail="Quedada no encontrada")

    if not _can_manage_meetup(db, meetup, current_user):
        raise HTTPException(status_code=403, detail="No autorizado")

    meetup.status = "done"
    db.commit()

    anyio.from_thread.run(
        broadcast,
        "MEETUP_DONE",
        {
            "meetup_id": meetup.id,
            "group_id": meetup.group_id,
            "status": meetup.status,
        },
    )

    return {"ok": True, "status": meetup.status}