from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from datetime import datetime
import secrets

from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.config import settings
from app.web.session import get_user_from_cookie

from app.models.group import Group
from app.models.user import User
from app.models.membership import GroupMember
from app.models.invite import GroupInvite
from app.models.meetup_participant import MeetupParticipant
from app.models.meetup import Meetup


router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _db() -> Session:
    return SessionLocal()


def _template_ctx(request: Request, db: Session, **extra):
    token = request.cookies.get("access_token")
    user = get_user_from_cookie(db, token)
    base = {
        "request": request,
        "user_email": user.email if user else None,
        "dev": settings.DEV,
    }
    base.update(extra)
    return base

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)

        if user:
            return RedirectResponse(url="/dashboard", status_code=302)

        ctx = _template_ctx(request, db, title="Inicio")
        return templates.TemplateResponse("index.html", ctx)
    finally:
        db.close()

@router.get("/login", response_class=HTMLResponse)
def login(request: Request):
    db = _db()
    try:
        ctx = _template_ctx(request, db, title="Login")
        return templates.TemplateResponse("login.html", ctx)
    finally:
        db.close()


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, sport: str | None = None, city: str | None = None):
    db = _db()
    try:
        stmt = select(Group)
        if sport:
            stmt = stmt.where(Group.sport == sport.lower().strip())
        if city:
            stmt = stmt.where(Group.city == city.strip())

        groups = db.execute(stmt).scalars().all()
        msg = request.query_params.get("msg")

        ctx = _template_ctx(
            request,
            db,
            title="Grupos",
            groups=groups,
            sport=sport,
            city=city,
            msg=msg,
        )
        return templates.TemplateResponse("groups.html", ctx)
    finally:
        db.close()


@router.get("/groups/new", response_class=HTMLResponse)
def group_new(request: Request):
    db = _db()
    try:
        ctx = _template_ctx(request, db, title="Crear grupo")
        return templates.TemplateResponse("group_new.html", ctx)
    finally:
        db.close()


@router.post("/groups/new")
def group_new_post(
    request: Request,
    name: str = Form(...),
    sport: str = Form(...),
    city: str = Form(...),
    is_private: str | None = Form(None),
):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/groups?msg=Necesitas sesión (usa Acceso DEV)", status_code=302)

        group = Group(
            name=name.strip(),
            sport=sport.lower().strip(),
            city=city.strip(),
            is_private=bool(is_private),
            owner_id=user.id,
        )
        db.add(group)
        db.commit()
        db.refresh(group)

        # el owner entra como miembro
        db.add(GroupMember(group_id=group.id, user_id=user.id))
        db.commit()

        return RedirectResponse(url=f"/groups/{group.id}?msg=Grupo creado", status_code=302)
    finally:
        db.close()


@router.get("/groups/{group_id}", response_class=HTMLResponse)
def group_detail(request: Request, group_id: int):
    db = _db()
    try:
        group = db.get(Group, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Grupo no encontrado")

        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)

        msg = request.query_params.get("msg")
        invite_token = request.query_params.get("invite")

        # Si viene invite y no hay sesión: manda a login conservando next
        if invite_token and not user:
            return RedirectResponse(
                url=f"/login?msg=Necesitas sesión para aceptar la invitación&next=/groups/{group_id}?invite={invite_token}",
                status_code=302,
            )

        # Si viene invite y hay sesión: validarlo y unir
        if invite_token and user:
            invite = db.execute(
                select(GroupInvite).where(GroupInvite.token == invite_token)
            ).scalar_one_or_none()

            if not invite:
                return RedirectResponse(
                    url=f"/groups/{group_id}?msg=Invitación no válida",
                    status_code=302,
                )

            if invite.group_id != group_id:
                return RedirectResponse(
                    url=f"/groups/{group_id}?msg=Invitación no válida para este grupo",
                    status_code=302,
                )

            if (not invite.is_active) or invite.revoked_at is not None:
                return RedirectResponse(
                    url=f"/groups/{group_id}?msg=Invitación no válida",
                    status_code=302,
                )

            if invite.expires_at and invite.expires_at < datetime.utcnow():
                return RedirectResponse(
                    url=f"/groups/{group_id}?msg=Invitación expirada",
                    status_code=302,
                )

            existing = db.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user.id,
                )
            ).scalar_one_or_none()

            if not existing:
                db.add(GroupMember(group_id=group_id, user_id=user.id))
                invite.uses += 1
                if invite.max_uses and invite.uses >= invite.max_uses:
                    invite.is_active = False
                db.commit()

            return RedirectResponse(
                url=f"/groups/{group_id}?msg=Te has unido al grupo",
                status_code=302,
            )

        # miembros
        member_rows = db.execute(
            select(User.email)
            .join(GroupMember, GroupMember.user_id == User.id)
            .where(GroupMember.group_id == group_id)
            .order_by(User.email.asc())
        ).all()
        members = [row[0] for row in member_rows]

        # is_member
        is_member = False
        if user:
            is_member = db.execute(
                select(GroupMember.user_id).where(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user.id,
                )
            ).first() is not None

        # meetups próximos (incluye open/full)
        meetups = db.execute(
            select(Meetup)
            .where(Meetup.group_id == group_id)
            .where(Meetup.status.in_(["open", "full"]))
            .where(Meetup.starts_at >= datetime.utcnow())
            .order_by(Meetup.starts_at.asc())
        ).scalars().all()

        meetup_ids = [m.id for m in meetups]

        # occupied_map
        occupied_map = {}
        if meetup_ids:
            rows = db.execute(
                select(MeetupParticipant.meetup_id, func.count().label("c"))
                .where(MeetupParticipant.meetup_id.in_(meetup_ids))
                .group_by(MeetupParticipant.meetup_id)
            ).all()
            occupied_map = {mid: int(c) for (mid, c) in rows}

        # going_ids
        going_ids = set()
        if user and meetup_ids:
            rows = db.execute(
                select(MeetupParticipant.meetup_id)
                .where(MeetupParticipant.user_id == user.id)
                .where(MeetupParticipant.meetup_id.in_(meetup_ids))
            ).all()
            going_ids = {r[0] for r in rows}

        # inyectar campos "pro" al objeto para template (sin tocar modelos)
        for mt in meetups:
            mt.participants_count = occupied_map.get(mt.id, 0)
            mt.is_joined = (mt.id in going_ids)

            # opcional: coherencia visual "full"
            if mt.capacity and mt.participants_count >= mt.capacity:
                mt.status = "full" if mt.status == "open" else mt.status

        ctx = _template_ctx(
            request,
            db,
            title=group.name,
            group=group,
            msg=msg,
            members=members,
            meetups=meetups,          # <-- ahora template usa m directamente
            is_member=is_member,
            invite_token=invite_token,
            user_id=user.id if user else None,  # <-- para owner tools en template
        )
        return templates.TemplateResponse("group_detail.html", ctx)
    finally:
        db.close()


@router.post("/meetups/{meetup_id}/join-web")
def join_meetup_web(request: Request, meetup_id: int):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        meetup = db.get(Meetup, meetup_id)
        if not meetup:
            raise HTTPException(status_code=404, detail="Quedada no encontrada")

        # Solo permitir apuntarse si está abierta
        if meetup.status != "open":
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=Quedada no abierta",
                status_code=302,
            )

        # Debe ser miembro del grupo
        is_member = db.execute(
            select(GroupMember.user_id).where(
                GroupMember.group_id == meetup.group_id,
                GroupMember.user_id == user.id,
            )
        ).first() is not None

        if not is_member:
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=Debes ser miembro del grupo",
                status_code=302,
            )

        try:
            # SQLite: bloquea escritura durante check+insert => reduce race conditions
            db.execute("BEGIN IMMEDIATE")

            # Si ya está apuntado (rápido)
            existing = db.execute(
                select(MeetupParticipant.id).where(
                    MeetupParticipant.meetup_id == meetup_id,
                    MeetupParticipant.user_id == user.id,
                )
            ).first()
            if existing:
                db.rollback()
                return RedirectResponse(
                    url=f"/groups/{meetup.group_id}?msg=Ya estabas apuntado",
                    status_code=302,
                )

            # Capacidad (si existe)
            if meetup.capacity:
                count = db.execute(
                    select(func.count())
                    .select_from(MeetupParticipant)
                    .where(MeetupParticipant.meetup_id == meetup_id)
                ).scalar_one()

                if count >= meetup.capacity:
                    # Marcar como full si corresponde
                    meetup.status = "full"
                    db.commit()
                    return RedirectResponse(
                        url=f"/groups/{meetup.group_id}?msg=Quedada completa",
                        status_code=302,
                    )

            # Insertar participación
            db.add(MeetupParticipant(meetup_id=meetup_id, user_id=user.id))
            db.flush()  # fuerza el INSERT aquí (salta IntegrityError si duplicado)

            # Si con este join se llena, marcar full
            if meetup.capacity:
                count2 = db.execute(
                    select(func.count())
                    .select_from(MeetupParticipant)
                    .where(MeetupParticipant.meetup_id == meetup_id)
                ).scalar_one()

                if count2 >= meetup.capacity:
                    meetup.status = "full"

            db.commit()
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=Apuntado a la quedada",
                status_code=302,
            )

        except IntegrityError:
            db.rollback()
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=Ya estabas apuntado",
                status_code=302,
            )

    finally:
        db.close()


@router.post("/groups/{group_id}/join-web")
def join_group_web(request: Request, group_id: int):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/groups?msg=Necesitas sesión (usa Acceso DEV)", status_code=302)

        group = db.get(Group, group_id)
        if not group:
            return RedirectResponse(url="/groups?msg=Grupo no encontrado", status_code=302)

        if group.is_private:
            return RedirectResponse(url="/groups?msg=Grupo privado: requiere invitación", status_code=302)

        existing = db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user.id,
            )
        ).scalar_one_or_none()

        if existing:
            return RedirectResponse(url="/groups?msg=Ya eras miembro", status_code=302)

        db.add(GroupMember(group_id=group_id, user_id=user.id))
        db.commit()
        return RedirectResponse(url="/groups?msg=Te has unido al grupo", status_code=302)
    finally:
        db.close()


@router.post("/groups/{group_id}/join-invite-web")
def join_invite_web(request: Request, group_id: int, token: str = Form(...)):
    db = _db()
    try:
        access = request.cookies.get("access_token")
        user = get_user_from_cookie(db, access)
        if not user:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Necesitas sesión", status_code=302)

        invite = db.execute(select(GroupInvite).where(GroupInvite.token == token.strip())).scalar_one_or_none()
        if not invite or not invite.is_active:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Invitación no válida", status_code=302)

        if invite.group_id != group_id:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Invitación no corresponde a este grupo", status_code=302)

        if invite.expires_at and invite.expires_at < datetime.utcnow():
            return RedirectResponse(url=f"/groups/{group_id}?msg=Invitación expirada", status_code=302)

        existing = db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user.id,
            )
        ).scalar_one_or_none()

        if existing:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Ya eras miembro", status_code=302)

        db.add(GroupMember(group_id=group_id, user_id=user.id))
        db.commit()
        return RedirectResponse(url=f"/groups/{group_id}?msg=Unido por invitación", status_code=302)
    finally:
        db.close()


@router.post("/groups/{group_id}/create-invite-web")
def create_invite_web(request: Request, group_id: int):
    db = _db()
    try:
        access = request.cookies.get("access_token")
        user = get_user_from_cookie(db, access)
        if not user:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Necesitas sesión", status_code=302)

        group = db.get(Group, group_id)
        if not group:
            return RedirectResponse(url="/groups?msg=Grupo no encontrado", status_code=302)

        if not group.is_private:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Solo para grupos privados", status_code=302)

        if group.owner_id != user.id:
            return RedirectResponse(url=f"/groups/{group_id}?msg=Solo el owner puede invitar", status_code=302)

        token = secrets.token_urlsafe(24)
        inv = GroupInvite(group_id=group_id, token=token, created_by=user.id, is_active=True)
        db.add(inv)
        db.commit()

        base_url = str(request.base_url).rstrip("/")
        invite_link = f"{base_url}/groups/{group_id}?invite={token}"

        return RedirectResponse(
            url=f"/groups/{group_id}?msg=Invitación creada: {invite_link}",
            status_code=302,
        )

    finally:
        db.close()

@router.post("/meetups/{meetup_id}/leave-web")
def leave_meetup_web(request: Request, meetup_id: int):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        meetup = db.get(Meetup, meetup_id)
        if not meetup:
            raise HTTPException(status_code=404, detail="Quedada no encontrada")

        row = db.execute(
            select(MeetupParticipant).where(
                MeetupParticipant.meetup_id == meetup_id,
                MeetupParticipant.user_id == user.id,
            )
        ).scalar_one_or_none()

        if not row:
            return RedirectResponse(url=f"/groups/{meetup.group_id}?msg=No estabas apuntado", status_code=302)

        db.delete(row)
        db.commit()

        # si estaba full y ahora hay hueco, reabrir
        if meetup.status == "full":
            meetup.status = "open"
            db.commit()

        return RedirectResponse(url=f"/groups/{meetup.group_id}?msg=Te has desapuntado", status_code=302)
    finally:
        db.close()

@router.post("/meetups/{meetup_id}/cancel-web")
def cancel_meetup_web(request: Request, meetup_id: int):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        meetup = db.get(Meetup, meetup_id)
        if not meetup:
            raise HTTPException(status_code=404, detail="Quedada no encontrada")

        if meetup.created_by != user.id:
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=Solo el creador puede cancelar",
                status_code=302,
            )

        if meetup.status in ["cancelled", "done"]:
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=La quedada ya no está abierta",
                status_code=302,
            )

        meetup.status = "cancelled"
        db.commit()

        return RedirectResponse(
            url=f"/groups/{meetup.group_id}?msg=Quedada cancelada",
            status_code=302,
        )
    finally:
        db.close()


@router.post("/meetups/{meetup_id}/done-web")
def done_meetup_web(request: Request, meetup_id: int):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        meetup = db.get(Meetup, meetup_id)
        if not meetup:
            raise HTTPException(status_code=404, detail="Quedada no encontrada")

        if meetup.created_by != user.id:
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=Solo el creador puede marcarla como hecha",
                status_code=302,
            )

        if meetup.status in ["cancelled", "done"]:
            return RedirectResponse(
                url=f"/groups/{meetup.group_id}?msg=La quedada ya no está abierta",
                status_code=302,
            )

        meetup.status = "done"
        db.commit()

        return RedirectResponse(
            url=f"/groups/{meetup.group_id}?msg=Quedada marcada como hecha",
            status_code=302,
        )
    finally:
        db.close()

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    db = _db()
    try:
        token = request.cookies.get("access_token")
        user = get_user_from_cookie(db, token)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        # Mis grupos
        my_groups = db.execute(
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.user_id == user.id)
            .order_by(Group.name.asc())
        ).scalars().all()

        # Próximas quedadas donde voy
        my_meetups = db.execute(
            select(Meetup, Group)
            .join(MeetupParticipant, MeetupParticipant.meetup_id == Meetup.id)
            .join(Group, Group.id == Meetup.group_id)
            .where(MeetupParticipant.user_id == user.id)
            .where(Meetup.starts_at >= datetime.utcnow())
            .where(Meetup.status.in_(["open", "full"]))
            .order_by(Meetup.starts_at.asc())
        ).all()

        ctx = _template_ctx(
            request, db,
            title="Mi panel",
            my_groups=my_groups,
            my_meetups=my_meetups,
        )
        return templates.TemplateResponse("dashboard.html", ctx)
    finally:
        db.close()
