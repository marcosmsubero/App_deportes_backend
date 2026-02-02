from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.database import Base, engine
from app.models.user import User  # noqa: F401
from app.models.group import Group  # noqa: F401
from app.models.membership import GroupMember  # noqa: F401
from app.models.invite import GroupInvite  # noqa: F401
from app.models.meetup import Meetup  # noqa: F401
from app.models.meetup_participant import MeetupParticipant  # noqa: F401

from app.api.routes.auth import router as auth_router
from app.api.routes.groups import router as groups_router
from app.api.routes.meetups import router as meetups_router
from app.api.routes.meetups_upcoming import router as meetups_upcoming_router  # ✅ NUEVO

from app.web.routes import router as web_router
from app.web.dev import router as dev_router

# ✅ SSE
from app.realtime.sse import router as sse_router


Base.metadata.create_all(bind=engine)

app = FastAPI(title="App Deportes API", version="0.1.0")

# ✅ CORS primero
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.1.51:5173",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ✅ Routers después
app.include_router(auth_router)
app.include_router(groups_router)

# ✅ IMPORTANTE: upcoming ANTES que /meetups/{meetup_id}
app.include_router(meetups_upcoming_router)  # ✅ NUEVO (primero)
app.include_router(meetups_router)           # ✅ después

# ✅ SSE
app.include_router(sse_router)

# ✅ Web (HTML + static)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(web_router)
app.include_router(dev_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "API App Deportes funcionando 🚀"}


@app.get("/health")
def health():
    return {"ok": True}
