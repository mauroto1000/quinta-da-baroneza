from datetime import date, datetime, time, timedelta
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.deps import require_admin, get_current_user
from app.auth import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    today = date.today()

    total_players = db.query(models.User).filter(models.User.role == models.UserRole.PLAYER).count()
    upcoming_groups = (
        db.query(models.Group)
        .join(models.TeeSlot)
        .filter(models.TeeSlot.slot_datetime >= datetime.utcnow())
        .count()
    )
    pending_requests = db.query(models.JoinRequest).filter(
        models.JoinRequest.status == models.RequestStatus.PENDING
    ).count()

    # Occupancy for next 7 days
    occupancy = []
    for i in range(7):
        d = today + timedelta(days=i)
        slots_count = (
            db.query(models.TeeSlot)
            .join(models.ScheduleBlock)
            .filter(models.ScheduleBlock.date == d)
            .count()
        )
        groups_count = (
            db.query(models.Group)
            .join(models.TeeSlot)
            .join(models.ScheduleBlock)
            .filter(models.ScheduleBlock.date == d)
            .count()
        )
        occupancy.append({"date": d, "slots": slots_count, "groups": groups_count})

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request, "user": user,
            "total_players": total_players,
            "upcoming_groups": upcoming_groups,
            "pending_requests": pending_requests,
            "occupancy": occupancy,
        },
    )


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
@router.get("/players", response_class=HTMLResponse)
def players_list(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    players = db.query(models.User).order_by(models.User.full_name).all()
    return templates.TemplateResponse(
        "admin/players.html",
        {"request": request, "user": user, "players": players, "UserRole": models.UserRole, "error": None, "success": None},
    )


@router.post("/players/new", response_class=HTMLResponse)
def create_player(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    whatsapp: str = Form(...),
    hcp_index: str = Form(""),
    role: str = Form("player"),
    db: Session = Depends(get_db),
):
    from app.routers.auth import DEFAULT_INITIAL_PASSWORD
    user = require_admin(request, db)
    email = email.lower().strip()

    if db.query(models.User).filter(models.User.email == email).first():
        players = db.query(models.User).order_by(models.User.full_name).all()
        return templates.TemplateResponse(
            "admin/players.html",
            {"request": request, "user": user, "players": players,
             "UserRole": models.UserRole, "error": "E-mail já cadastrado.", "success": None},
        )

    hcp = None
    if hcp_index.strip():
        try:
            hcp = float(hcp_index.replace(",", "."))
        except ValueError:
            pass

    new_user = models.User(
        full_name=full_name.strip(),
        email=email,
        whatsapp=whatsapp.strip(),
        hcp_index=hcp,
        password_hash=hash_password(DEFAULT_INITIAL_PASSWORD),
        role=models.UserRole(role),
        must_change_password=True,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/admin/players", status_code=302)


@router.get("/players/{player_id}/edit", response_class=HTMLResponse)
def edit_player_page(player_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    player = db.query(models.User).filter(models.User.id == player_id).first()
    if not player:
        return RedirectResponse("/admin/players", status_code=302)
    return templates.TemplateResponse(
        "admin/edit_player.html",
        {"request": request, "user": admin, "player": player, "UserRole": models.UserRole, "error": None},
    )


@router.post("/players/{player_id}/edit", response_class=HTMLResponse)
def edit_player_submit(
    player_id: int,
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    whatsapp: str = Form(...),
    hcp_index: str = Form(""),
    role: str = Form("player"),
    is_active: str = Form("on"),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    player = db.query(models.User).filter(models.User.id == player_id).first()
    if not player:
        return RedirectResponse("/admin/players", status_code=302)

    email = email.lower().strip()
    conflict = db.query(models.User).filter(
        models.User.email == email, models.User.id != player_id
    ).first()
    if conflict:
        return templates.TemplateResponse(
            "admin/edit_player.html",
            {"request": request, "user": admin, "player": player,
             "UserRole": models.UserRole, "error": "E-mail já cadastrado por outro usuário."},
        )

    player.full_name = full_name.strip()
    player.email = email
    player.whatsapp = whatsapp.strip()
    player.role = models.UserRole(role)
    player.is_active = is_active == "on"

    hcp_str = hcp_index.strip()
    if hcp_str:
        try:
            player.hcp_index = float(hcp_str.replace(",", "."))
        except ValueError:
            pass
    else:
        player.hcp_index = None

    if new_password.strip():
        if len(new_password) < 6:
            return templates.TemplateResponse(
                "admin/edit_player.html",
                {"request": request, "user": admin, "player": player,
                 "UserRole": models.UserRole, "error": "A nova senha deve ter ao menos 6 caracteres."},
            )
        player.password_hash = hash_password(new_password)

    db.commit()
    return RedirectResponse("/admin/players", status_code=302)


@router.post("/players/{player_id}/delete", response_class=HTMLResponse)
def delete_player(player_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    player = db.query(models.User).filter(models.User.id == player_id).first()
    if player and player.id != admin.id:
        db.delete(player)
        db.commit()
    return RedirectResponse("/admin/players", status_code=302)


# ---------------------------------------------------------------------------
# Schedule management
# ---------------------------------------------------------------------------
@router.get("/schedule", response_class=HTMLResponse)
def admin_schedule(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    today = date.today()
    blocks = (
        db.query(models.ScheduleBlock)
        .filter(models.ScheduleBlock.date >= today)
        .order_by(models.ScheduleBlock.date, models.ScheduleBlock.tee_number)
        .all()
    )
    return templates.TemplateResponse(
        "admin/schedule.html",
        {"request": request, "user": user, "blocks": blocks, "today": today,
         "TeeNumber": models.TeeNumber, "error": None},
    )


@router.post("/schedule/new", response_class=HTMLResponse)
def create_schedule_block(
    request: Request,
    block_date: str = Form(...),
    tee_number: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    interval_minutes: int = Form(10),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)

    try:
        d = date.fromisoformat(block_date)
        st = time.fromisoformat(start_time)
        et = time.fromisoformat(end_time)
    except ValueError as e:
        blocks = db.query(models.ScheduleBlock).filter(
            models.ScheduleBlock.date >= date.today()
        ).order_by(models.ScheduleBlock.date).all()
        return templates.TemplateResponse(
            "admin/schedule.html",
            {"request": request, "user": admin, "blocks": blocks, "today": date.today(),
             "TeeNumber": models.TeeNumber, "error": f"Data/hora inválida: {e}"},
        )

    if st >= et:
        blocks = db.query(models.ScheduleBlock).filter(
            models.ScheduleBlock.date >= date.today()
        ).order_by(models.ScheduleBlock.date).all()
        return templates.TemplateResponse(
            "admin/schedule.html",
            {"request": request, "user": admin, "blocks": blocks, "today": date.today(),
             "TeeNumber": models.TeeNumber, "error": "Horário de início deve ser antes do horário de término."},
        )

    existing = db.query(models.ScheduleBlock).filter(
        models.ScheduleBlock.date == d,
        models.ScheduleBlock.tee_number == models.TeeNumber(tee_number),
    ).first()
    if existing:
        blocks = db.query(models.ScheduleBlock).filter(
            models.ScheduleBlock.date >= date.today()
        ).order_by(models.ScheduleBlock.date).all()
        return templates.TemplateResponse(
            "admin/schedule.html",
            {"request": request, "user": admin, "blocks": blocks, "today": date.today(),
             "TeeNumber": models.TeeNumber, "error": "Já existe um bloco para esta data e tee."},
        )

    block = models.ScheduleBlock(
        date=d,
        tee_number=models.TeeNumber(tee_number),
        start_time=st,
        end_time=et,
        interval_minutes=interval_minutes,
        created_by=admin.id,
    )
    db.add(block)
    db.flush()

    # Generate TeeSlots
    _generate_slots(db, block)
    db.commit()
    return RedirectResponse("/admin/schedule", status_code=302)


def _generate_slots(db: Session, block: models.ScheduleBlock) -> None:
    """Generate TeeSlot records for a ScheduleBlock."""
    current = datetime.combine(block.date, block.start_time)
    end = datetime.combine(block.date, block.end_time)
    while current <= end:
        existing = db.query(models.TeeSlot).filter(
            models.TeeSlot.slot_datetime == current,
            models.TeeSlot.tee_number == block.tee_number,
        ).first()
        if not existing:
            slot = models.TeeSlot(
                schedule_block_id=block.id,
                slot_datetime=current,
                tee_number=block.tee_number,
            )
            db.add(slot)
        current += timedelta(minutes=block.interval_minutes)


@router.post("/schedule/{block_id}/delete", response_class=HTMLResponse)
def delete_schedule_block(block_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    block = db.query(models.ScheduleBlock).filter(models.ScheduleBlock.id == block_id).first()
    if block:
        db.delete(block)
        db.commit()
    return RedirectResponse("/admin/schedule", status_code=302)


@router.post("/schedule/{block_id}/toggle-block", response_class=HTMLResponse)
def toggle_block(
    block_id: int,
    request: Request,
    block_reason: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    block = db.query(models.ScheduleBlock).filter(models.ScheduleBlock.id == block_id).first()
    if block:
        block.is_blocked = not block.is_blocked
        block.block_reason = block_reason.strip() or None
        db.commit()
    return RedirectResponse("/admin/schedule", status_code=302)


# ---------------------------------------------------------------------------
# Groups management
# ---------------------------------------------------------------------------
@router.get("/groups", response_class=HTMLResponse)
def admin_groups(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    groups = (
        db.query(models.Group)
        .join(models.TeeSlot)
        .filter(models.TeeSlot.slot_datetime >= datetime.utcnow())
        .order_by(models.TeeSlot.slot_datetime)
        .all()
    )
    return templates.TemplateResponse(
        "admin/groups.html",
        {"request": request, "user": user, "groups": groups,
         "GroupStatus": models.GroupStatus, "RequestStatus": models.RequestStatus},
    )


@router.post("/groups/{group_id}/move-player", response_class=HTMLResponse)
def move_player(
    group_id: int,
    request: Request,
    user_id: int = Form(...),
    target_group_id: int = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    membership = db.query(models.GroupMember).filter(
        models.GroupMember.group_id == group_id,
        models.GroupMember.user_id == user_id,
        models.GroupMember.status == models.RequestStatus.ACCEPTED,
    ).first()
    target_group = db.query(models.Group).filter(models.Group.id == target_group_id).first()

    if membership and target_group and not target_group.is_full:
        membership.group_id = target_group_id
        db.commit()

    return RedirectResponse("/admin/groups", status_code=302)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@router.get("/config", response_class=HTMLResponse)
def admin_config(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    configs = {c.key: c for c in db.query(models.SystemConfig).all()}
    return templates.TemplateResponse(
        "admin/config.html",
        {"request": request, "user": user, "configs": configs, "success": False},
    )


@router.post("/config", response_class=HTMLResponse)
def save_config(
    request: Request,
    booking_window_days: str = Form("14"),
    request_timeout_hours: str = Form("1"),
    cancel_deadline_hours: str = Form("24"),
    max_groups_per_slot: str = Form("6"),
    evolution_api_url: str = Form(""),
    evolution_api_key: str = Form(""),
    evolution_instance: str = Form(""),
    app_base_url: str = Form(""),
    club_name: str = Form("Quinta da Baroneza Golfe Clube"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    updates = {
        "booking_window_days": booking_window_days.strip(),
        "request_timeout_hours": request_timeout_hours.strip(),
        "cancel_deadline_hours": cancel_deadline_hours.strip(),
        "max_groups_per_slot": max_groups_per_slot.strip(),
        "evolution_api_url": evolution_api_url.strip(),
        "evolution_api_key": evolution_api_key.strip(),
        "evolution_instance": evolution_instance.strip(),
        "app_base_url": app_base_url.strip(),
        "club_name": club_name.strip(),
    }
    for key, value in updates.items():
        cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if cfg:
            cfg.value = value
            cfg.updated_at = datetime.utcnow()
            cfg.updated_by = admin.id
        else:
            cfg = models.SystemConfig(key=key, value=value, updated_by=admin.id)
            db.add(cfg)
    db.commit()

    configs = {c.key: c for c in db.query(models.SystemConfig).all()}
    return templates.TemplateResponse(
        "admin/config.html",
        {"request": request, "user": admin, "configs": configs, "success": True},
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request, report_date: str = None, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    selected_date = None
    report_data = []

    if report_date:
        try:
            selected_date = date.fromisoformat(report_date)
            blocks = (
                db.query(models.ScheduleBlock)
                .filter(models.ScheduleBlock.date == selected_date)
                .order_by(models.ScheduleBlock.tee_number)
                .all()
            )
            for block in blocks:
                slots = (
                    db.query(models.TeeSlot)
                    .filter(models.TeeSlot.schedule_block_id == block.id)
                    .order_by(models.TeeSlot.slot_datetime)
                    .all()
                )
                slot_info = []
                for slot in slots:
                    groups = db.query(models.Group).filter(models.Group.tee_slot_id == slot.id).all()
                    total_players = sum(
                        1 for g in groups
                        for m in g.members
                        if m.status == models.RequestStatus.ACCEPTED
                    )
                    slot_info.append({"slot": slot, "groups": groups, "total_players": total_players})
                report_data.append({"block": block, "slots": slot_info})
        except ValueError:
            pass

    return templates.TemplateResponse(
        "admin/reports.html",
        {
            "request": request, "user": user,
            "selected_date": selected_date,
            "report_data": report_data,
            "GroupStatus": models.GroupStatus,
            "RequestStatus": models.RequestStatus,
        },
    )
