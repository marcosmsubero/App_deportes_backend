from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.user import User

router = APIRouter(prefix="/dev", tags=["dev"])


def _only_dev():
    # Activa DEV=true en backend/.env
    if getattr(settings, "DEV", False) is not True:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("", response_class=HTMLResponse)
def dev_home(_=Depends(_only_dev)):
    return """
    <h2>DEV panel</h2>
    <ul>
      <li><a href="/dev/quick-login">Acceso DEV (sin credenciales)</a></li>
      <li><a href="/dev/login?email=dev@demo.com">Login como dev@demo.com (si existe)</a></li>
      <li><a href="/groups">Ir a /groups (web)</a></li>
      <li><a href="/docs">Ir a /docs (API)</a></li>
    </ul>
    """


@router.get("/login")
def dev_login(email: str, db: Session = Depends(get_db), _=Depends(_only_dev)):
    # Esto solo loguea si el usuario YA existe en DB
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Ese usuario no existe (usa /dev/quick-login)")

    token = create_access_token(str(user.id))
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    return resp


@router.get("/quick-login")
def dev_quick_login(db: Session = Depends(get_db), _=Depends(_only_dev)):
    # Crea o reutiliza un usuario DEV con password real "123456"
    email = "dev@demo.com"
    desired_hash = hash_password("123456")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        user = User(email=email, hashed_password=desired_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Si el user ya existía con hash inválido, lo reparamos
        user.hashed_password = desired_hash
        db.commit()
        db.refresh(user)

    token = create_access_token(str(user.id))
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    return resp


@router.get("/logout")
def dev_logout(_=Depends(_only_dev)):
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("access_token")
    return resp
