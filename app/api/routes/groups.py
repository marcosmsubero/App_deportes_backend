from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime
import secrets
import anyio

from app.api.deps import get_db
from app.core.auth import get_current_user
from app.models.group import Group
from app.models.membership import GroupMember
from app.models.user import User
from app.schemas.group import GroupCreate, GroupPublic
from app.models.invite import GroupInvite
from app.schemas.invite import InviteCreateRequest, InvitePublic

# ✅ Para borrado completo
from app.models.meetup import Meetup
from app.models.meetup_participant import MeetupParticipant

# ✅ SSE
from app.realtime.sse import broadcast


router = APIRouter(prefix="/groups", tags=["groups"])


def _require_owner(group: Group, current_user: User):
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el owner puede hacer esto")


def _require_member(db: Session, group_id: int, user_id: int) -> GroupMember:
    m = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=403, detail="Debes ser miembro del grupo")
    return m


def _require_owner_or_mod(db: Session, group: Group, current_user: User) -> GroupMember:
    if group.owner_id == current_user.id:
        # owner implícito
        return GroupMember(group_id=group.id, user_id=current_user.id, role="owner")  # dummy
    m = _require_member(db, group.id, current_user.id)
    if m.role not in ("mod", "owner"):
        raise HTTPException(status_code=403, detail="No autorizado")
    return m


# ✅ NUEVO: eliminar grupo + TODO lo relacionado + SSE a todos
@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    # Admin = owner o mod
    _require_owner_or_mod(db, group, current_user)

    # 1) Meetups del grupo
    meetups = db.execute(select(Meetup).where(Meetup.group_id == group_id)).scalars().all()
    meetup_ids = [m.id for m in meetups]

    # 1a) Participantes de meetups
    if meetup_ids:
        parts = db.execute(
            select(MeetupParticipant).where(MeetupParticipant.meetup_id.in_(meetup_ids))
        ).scalars().all()
        for p in parts:
            db.delete(p)

        # 1b) Meetups
        for m in meetups:
            db.delete(m)

    # 2) Invitaciones del grupo
    invites = db.execute(
        select(GroupInvite).where(GroupInvite.group_id == group_id)
    ).scalars().all()
    for inv in invites:
        db.delete(inv)

    # 3) Miembros del grupo
    members = db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id)
    ).scalars().all()
    for mem in members:
        db.delete(mem)

    # 4) Grupo
    db.delete(group)
    db.commit()

    # 🔴 SSE: avisar a TODOS los clientes conectados
    anyio.from_thread.run(
        broadcast,
        "GROUP_DELETED",
        {"group_id": group_id},
    )

    return {"ok": True, "deleted_group_id": group_id}


@router.post("/{group_id}/invites", response_model=InvitePublic)
def create_invite(
    group_id: int,
    payload: InviteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    _require_owner(group, current_user)

    if not group.is_private:
        raise HTTPException(status_code=400, detail="Este grupo no es privado")

    token = secrets.token_urlsafe(24)
    invite = GroupInvite(
        group_id=group_id,
        token=token,
        created_by=current_user.id,
        expires_at=payload.expires_at,
        is_active=True,
        max_uses=payload.max_uses,
        uses=0,
        revoked_at=None,
    )

    db.add(invite)
    db.commit()
    db.refresh(invite)

    return InvitePublic(
        token=invite.token,
        group_id=invite.group_id,
        expires_at=invite.expires_at,
        is_active=invite.is_active,
        uses=invite.uses,
        max_uses=invite.max_uses,
        revoked_at=invite.revoked_at,
    )


@router.post("/join-by-invite/{token}")
def join_by_invite(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invite = db.execute(select(GroupInvite).where(GroupInvite.token == token)).scalar_one_or_none()
    if not invite or not invite.is_active or invite.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Invitación no válida")

    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invitación expirada")

    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        raise HTTPException(status_code=409, detail="Invitación agotada")

    group = db.get(Group, invite.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    existing = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if existing:
        return {"ok": True, "message": "Ya eres miembro"}

    db.add(GroupMember(group_id=group.id, user_id=current_user.id))
    invite.uses += 1
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        invite.is_active = False
    db.commit()
    return {"ok": True, "message": "Te has unido al grupo (por invitación)"}


@router.post("", response_model=GroupPublic)
def create_group(
    payload: GroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = Group(
        name=payload.name.strip(),
        sport=payload.sport.lower().strip(),
        city=payload.city.strip(),
        is_private=payload.is_private,
        owner_id=current_user.id,
    )
    db.add(group)
    db.commit()
    db.refresh(group)

    member = GroupMember(group_id=group.id, user_id=current_user.id)
    db.add(member)
    db.commit()

    return GroupPublic(
        id=group.id,
        name=group.name,
        sport=group.sport,
        city=group.city,
        is_private=group.is_private,
        owner_id=group.owner_id,
    )


@router.get("", response_model=list[GroupPublic])
def list_groups(
    sport: str | None = None,
    city: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Group)
    if sport:
        stmt = stmt.where(Group.sport == sport.lower().strip())
    if city:
        stmt = stmt.where(Group.city == city.strip())
    groups = db.execute(stmt).scalars().all()
    return [GroupPublic(**g.__dict__) for g in groups]


@router.get("/{group_id}", response_model=GroupPublic)
def get_group(group_id: int, db: Session = Depends(get_db)):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return GroupPublic(**group.__dict__)


@router.post("/{group_id}/join")
def join_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if group.is_private:
        raise HTTPException(status_code=403, detail="Grupo privado: requiere invitación")

    existing = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if existing:
        return {"ok": True, "message": "Ya eres miembro"}

    db.add(GroupMember(group_id=group_id, user_id=current_user.id))
    db.commit()
    return {"ok": True, "message": "Te has unido al grupo"}


@router.post("/{group_id}/members/{user_id}/role")
def set_member_role(
    group_id: int,
    user_id: int,
    role: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    _require_owner(group, current_user)

    if role not in ("member", "mod"):
        raise HTTPException(status_code=400, detail="Role inválido (member/mod)")

    target = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no es miembro")

    target.role = role
    db.commit()
    return {"ok": True, "user_id": user_id, "role": role}


@router.post("/{group_id}/members/{user_id}/kick")
def kick_member(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    _require_owner_or_mod(db, group, current_user)

    if user_id == group.owner_id:
        raise HTTPException(status_code=400, detail="No puedes expulsar al owner")

    target = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no es miembro")

    db.delete(target)
    db.commit()
    return {"ok": True, "kicked_user_id": user_id}


@router.get("/{group_id}/members/me")
def my_role(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if group.owner_id == current_user.id:
        return {"role": "owner"}

    m = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if not m:
        return {"role": None}

    return {"role": m.role}


@router.get("/{group_id}/members")
def list_members(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    members = db.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.email.asc())
    ).all()

    return [
        {"user_id": u.id, "email": u.email, "role": m.role}
        for (m, u) in members
    ]


@router.get("/{group_id}/invites", response_model=list[InvitePublic])
def list_invites(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el owner puede ver invitaciones")

    invites = db.execute(
        select(GroupInvite)
        .where(GroupInvite.group_id == group_id)
        .order_by(GroupInvite.created_at.desc())
    ).scalars().all()

    return invites


@router.post("/{group_id}/invites/{token}/revoke")
def revoke_invite(
    group_id: int,
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el owner puede revocar")

    invite = db.execute(
        select(GroupInvite).where(
            GroupInvite.group_id == group_id,
            GroupInvite.token == token,
        )
    ).scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")

    invite.is_active = False
    invite.revoked_at = datetime.utcnow()
    db.commit()

    return {"ok": True}
