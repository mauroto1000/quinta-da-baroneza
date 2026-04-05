from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.deps import get_current_user, get_system_config
from app.services.slot_generator import ensure_slots_for_date, ensure_slots_for_window

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

    # Auto-gera slots para toda a janela
    ensure_slots_for_window(db, window)

    blocks = (
        db.query(models.ScheduleBlock)
        .filter(
            models.ScheduleBlock.date >= today,
            models.ScheduleBlock.date <= end_date,
        )
        .order_by(models.ScheduleBlock.date, models.ScheduleBlock.tee_number)
        .all()
    )

    # Slots com grupos para o período inteiro (uma só query)
    slots_with_groups = (
        db.query(models.TeeSlot)
        .join(models.ScheduleBlock)
        .join(models.Group, models.Group.tee_slot_id == models.TeeSlot.id)
        .filter(
            models.ScheduleBlock.date >= today,
            models.ScheduleBlock.date <= end_date,
        )
        .all()
    )

    # Monta índice: date -> lista de (horário, nº jogadores)
    from collections import defaultdict
    day_occupancy = defaultdict(list)
    for slot in slots_with_groups:
        players = sum(
            1 for g in slot.groups
            for m in g.members
            if m.status == models.RequestStatus.ACCEPTED
        )
        if players > 0:
            day_occupancy[slot.slot_datetime.date()].append({
                "time": slot.slot_datetime,
                "players": players,
                "tee": slot.tee_number.value,
            })

    dates = []
    for i in range(window + 1):
        d = today + timedelta(days=i)
        day_blocks = [b for b in blocks if b.date == d and not b.is_blocked]
        all_blocked = all(b.is_blocked for b in blocks if b.date == d) and any(b.date == d for b in blocks)
        occupied = sorted(day_occupancy.get(d, []), key=lambda x: x["time"])
        dates.append({
            "date": d,
            "blocks": day_blocks,
            "all_blocked": all_blocked,
            "occupied": occupied,
            "total_players": sum(o["players"] for o in occupied),
            "total_slots": len(occupied),
        })

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

    # Auto-gera slots para este dia se ainda não existirem
    ensure_slots_for_date(db, selected_date)

    blocks = (
        db.query(models.ScheduleBlock)
        .filter(models.ScheduleBlock.date == selected_date)
        .order_by(models.ScheduleBlock.tee_number)
        .all()
    )

    # Indexa slots por (slot_datetime, tee_number) para montar visão por horário
    slot_map = {}  # (datetime, tee_number) -> {slot, groups, user_in_slot}
    all_datetimes = set()

    for block in blocks:
        if block.is_blocked:
            continue
        slots = (
            db.query(models.TeeSlot)
            .filter(
                models.TeeSlot.schedule_block_id == block.id,
                models.TeeSlot.is_blocked == False,
            )
            .order_by(models.TeeSlot.slot_datetime)
            .all()
        )
        for slot in slots:
            all_datetimes.add(slot.slot_datetime)
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
            slot_map[(slot.slot_datetime, block.tee_number)] = {
                "slot": slot,
                "groups": groups,
                "user_in_slot": user_in_slot,
            }

    user_in_day = any(v["user_in_slot"] for v in slot_map.values())

    # Monta lista de horários, cada um com uma entrada por tee
    time_slots = []
    for dt in sorted(all_datetimes):
        tee_entries = []
        for block in blocks:
            key = (dt, block.tee_number)
            if block.is_blocked:
                tee_entries.append({
                    "tee_number": block.tee_number,
                    "slot": None,
                    "groups": [],
                    "user_in_slot": False,
                    "is_blocked": True,
                    "block_reason": block.block_reason,
                })
            elif key in slot_map:
                entry = slot_map[key]
                tee_entries.append({
                    "tee_number": block.tee_number,
                    "slot": entry["slot"],
                    "groups": entry["groups"],
                    "user_in_slot": entry["user_in_slot"],
                    "is_blocked": False,
                    "block_reason": None,
                })
        time_slots.append({"datetime": dt, "tees": tee_entries})

    return templates.TemplateResponse(
        "schedule/day.html",
        {
            "request": request,
            "user": user,
            "selected_date": selected_date,
            "blocks": blocks,
            "time_slots": time_slots,
            "user_in_day": user_in_day,
            "GroupStatus": models.GroupStatus,
            "RequestStatus": models.RequestStatus,
        },
    )
