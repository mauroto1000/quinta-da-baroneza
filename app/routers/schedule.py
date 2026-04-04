from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.deps import get_current_user, get_system_config

router = APIRouter(prefix="/schedule", tags=["schedule"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def schedule_index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    window = int(get_system_config(db, "booking_window_days", "14"))
    today = date.today()
    end_date = today + timedelta(days=window)

    # Get all schedule blocks in the window
    blocks = (
        db.query(models.ScheduleBlock)
        .filter(
            models.ScheduleBlock.date >= today,
            models.ScheduleBlock.date <= end_date,
        )
        .order_by(models.ScheduleBlock.date, models.ScheduleBlock.tee_number)
        .all()
    )

    # Build date list
    dates = []
    for i in range(window + 1):
        d = today + timedelta(days=i)
        day_blocks = [b for b in blocks if b.date == d]
        dates.append({"date": d, "blocks": day_blocks})

    return templates.TemplateResponse(
        "schedule/index.html",
        {"request": request, "user": user, "dates": dates, "today": today},
    )


@router.get("/day/{day_date}", response_class=HTMLResponse)
def schedule_day(day_date: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    try:
        selected_date = date.fromisoformat(day_date)
    except ValueError:
        return RedirectResponse("/schedule", status_code=302)

    blocks = (
        db.query(models.ScheduleBlock)
        .filter(models.ScheduleBlock.date == selected_date)
        .order_by(models.ScheduleBlock.tee_number)
        .all()
    )

    # For each block, load its slots and groups
    slots_data = []
    for block in blocks:
        slots = (
            db.query(models.TeeSlot)
            .filter(models.TeeSlot.schedule_block_id == block.id)
            .order_by(models.TeeSlot.slot_datetime)
            .all()
        )
        for slot in slots:
            groups = (
                db.query(models.Group)
                .filter(models.Group.tee_slot_id == slot.id)
                .all()
            )
            user_in_slot = any(
                m.user_id == user.id and m.status == models.RequestStatus.ACCEPTED
                for g in groups
                for m in g.members
            )
            slots_data.append({
                "slot": slot,
                "groups": groups,
                "user_in_slot": user_in_slot,
                "available_spots": sum(g.available_spots for g in groups if g.status != models.GroupStatus.FULL),
                "total_groups": len(groups),
            })

    return templates.TemplateResponse(
        "schedule/day.html",
        {
            "request": request,
            "user": user,
            "selected_date": selected_date,
            "blocks": blocks,
            "slots_data": slots_data,
            "GroupStatus": models.GroupStatus,
            "RequestStatus": models.RequestStatus,
        },
    )
