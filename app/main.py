from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.database import engine, SessionLocal
from app import models
from app.models import DEFAULT_CONFIGS
from app.routers import auth, schedule, groups, requests, admin
from app.deps import get_current_user


def init_db():
    models.Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        # Seed default configs
        for key, (value, description) in DEFAULT_CONFIGS.items():
            existing = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
            if not existing:
                db.add(models.SystemConfig(key=key, value=value, description=description))
        db.commit()
    finally:
        db.close()


scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.services.tasks import check_expired_steps
    scheduler.add_job(check_expired_steps, "interval", minutes=1, id="check_expired_steps")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Quinta da Baroneza – Agendamento de Tee", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# Routers
app.include_router(auth.router)
app.include_router(schedule.router)
app.include_router(groups.router)
app.include_router(requests.router)
app.include_router(admin.router)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
        if not user:
            return RedirectResponse("/auth/login", status_code=302)
        return RedirectResponse("/schedule", status_code=302)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Jinja2 global helpers
# ---------------------------------------------------------------------------
def _format_dt(value, fmt="%d/%m/%Y %H:%M"):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime(fmt)


def _format_date(value, fmt="%d/%m/%Y"):
    if not value:
        return ""
    return value.strftime(fmt)


def _format_time(value, fmt="%H:%M"):
    if not value:
        return ""
    return value.strftime(fmt)


templates.env.filters["dt"] = _format_dt
templates.env.filters["date"] = _format_date
templates.env.filters["time"] = _format_time

# Also add to each router's template instance  (they share the same directory so Jinja2 uses the same env)
from app.routers import auth as auth_router, schedule as sched_router, groups as groups_router
from app.routers import requests as req_router, admin as admin_router

for mod in [auth_router, sched_router, groups_router, req_router, admin_router]:
    mod.templates.env.filters["dt"] = _format_dt
    mod.templates.env.filters["date"] = _format_date
    mod.templates.env.filters["time"] = _format_time
