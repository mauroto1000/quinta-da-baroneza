from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.deps import get_current_user, require_login
from app.services import notifications

router = APIRouter(prefix="/groups", tags=["groups"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/new/{slot_id}", response_class=HTMLResponse)
def new_group_page(slot_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    slot = db.query(models.TeeSlot).filter(models.TeeSlot.id == slot_id).first()
    if not slot or slot.is_blocked:
        return RedirectResponse("/schedule", status_code=302)

    if slot.slot_datetime <= datetime.utcnow():
        return RedirectResponse(f"/schedule/day/{slot.slot_datetime.date()}", status_code=302)

    # Check if user already has a group in this slot
    existing = (
        db.query(models.GroupMember)
        .join(models.Group)
        .filter(
            models.Group.tee_slot_id == slot_id,
            models.GroupMember.user_id == user.id,
            models.GroupMember.status == models.RequestStatus.ACCEPTED,
        )
        .first()
    )
    if existing:
        return templates.TemplateResponse(
            "groups/new.html",
            {"request": request, "user": user, "slot": slot, "error": "Você já tem um grupo neste horário.", "GroupStatus": models.GroupStatus},
        )

    return templates.TemplateResponse(
        "groups/new.html",
        {"request": request, "user": user, "slot": slot, "error": None, "GroupStatus": models.GroupStatus},
    )


@router.post("/new/{slot_id}", response_class=HTMLResponse)
def create_group(
    slot_id: int,
    request: Request,
    status: str = Form("mixed"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    slot = db.query(models.TeeSlot).filter(models.TeeSlot.id == slot_id).first()
    if not slot or slot.is_blocked:
        return RedirectResponse("/schedule", status_code=302)

    # Validate status value
    try:
        group_status = models.GroupStatus(status)
    except ValueError:
        group_status = models.GroupStatus.MIXED

    # Check user not already in slot
    existing = (
        db.query(models.GroupMember)
        .join(models.Group)
        .filter(
            models.Group.tee_slot_id == slot_id,
            models.GroupMember.user_id == user.id,
            models.GroupMember.status == models.RequestStatus.ACCEPTED,
        )
        .first()
    )
    if existing:
        return RedirectResponse(f"/schedule/day/{slot.slot_datetime.date().isoformat()}", status_code=302)

    group = models.Group(
        tee_slot_id=slot_id,
        leader_id=user.id,
        status=group_status,
        notes=notes.strip() or None,
    )
    db.add(group)
    db.flush()

    # Leader is the first member
    membership = models.GroupMember(
        group_id=group.id,
        user_id=user.id,
        status=models.RequestStatus.ACCEPTED,
    )
    db.add(membership)
    db.commit()

    return RedirectResponse(f"/groups/{group.id}", status_code=302)


@router.get("/{group_id}", response_class=HTMLResponse)
def group_detail(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        return RedirectResponse("/schedule", status_code=302)

    is_member = any(
        m.user_id == user.id and m.status == models.RequestStatus.ACCEPTED
        for m in group.members
    )
    is_leader = group.leader_id == user.id

    # Pending join request steps for this group (leader needs to respond)
    pending_steps = []
    if is_leader:
        pending_steps = (
            db.query(models.JoinRequestStep)
            .filter(
                models.JoinRequestStep.group_id == group_id,
                models.JoinRequestStep.status == models.StepStatus.PENDING,
            )
            .all()
        )

    return templates.TemplateResponse(
        "groups/detail.html",
        {
            "request": request,
            "user": user,
            "group": group,
            "is_member": is_member,
            "is_leader": is_leader,
            "pending_steps": pending_steps,
            "GroupStatus": models.GroupStatus,
            "RequestStatus": models.RequestStatus,
            "StepStatus": models.StepStatus,
        },
    )


@router.post("/{group_id}/update-status", response_class=HTMLResponse)
def update_group_status(
    group_id: int,
    request: Request,
    status: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group or group.leader_id != user.id:
        return RedirectResponse("/schedule", status_code=302)

    try:
        group.status = models.GroupStatus(status)
    except ValueError:
        pass
    group.notes = notes.strip() or None
    db.commit()
    return RedirectResponse(f"/groups/{group_id}", status_code=302)


@router.post("/{group_id}/leave", response_class=HTMLResponse)
def leave_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        return RedirectResponse("/schedule", status_code=302)

    if group.leader_id == user.id:
        # Leader leaving — disband or transfer (for simplicity: disband if alone, error otherwise)
        confirmed = [m for m in group.members if m.status == models.RequestStatus.ACCEPTED and m.user_id != user.id]
        if confirmed:
            return templates.TemplateResponse(
                "groups/detail.html",
                {
                    "request": request, "user": user, "group": group,
                    "is_member": True, "is_leader": True, "pending_steps": [],
                    "error": "Você é o responsável do grupo. Transfira a liderança antes de sair, ou remova os outros membros.",
                    "GroupStatus": models.GroupStatus,
                    "RequestStatus": models.RequestStatus,
                    "StepStatus": models.StepStatus,
                },
            )
        # No other members — delete group
        db.delete(group)
        db.commit()
        return RedirectResponse("/schedule", status_code=302)

    membership = (
        db.query(models.GroupMember)
        .filter(
            models.GroupMember.group_id == group_id,
            models.GroupMember.user_id == user.id,
            models.GroupMember.status == models.RequestStatus.ACCEPTED,
        )
        .first()
    )
    if membership:
        membership.status = models.RequestStatus.CANCELLED
        # Re-open group if it was full
        if group.status == models.GroupStatus.FULL:
            group.status = models.GroupStatus.MIXED
        db.commit()
        notifications.notify_group_member_cancelled(db, group, user)

    return RedirectResponse(f"/schedule/day/{group.tee_slot.slot_datetime.date().isoformat()}", status_code=302)


@router.get("/my", response_class=HTMLResponse)
def my_groups(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    memberships = (
        db.query(models.GroupMember)
        .filter(
            models.GroupMember.user_id == user.id,
            models.GroupMember.status == models.RequestStatus.ACCEPTED,
        )
        .join(models.Group)
        .join(models.TeeSlot)
        .order_by(models.TeeSlot.slot_datetime)
        .all()
    )

    return templates.TemplateResponse(
        "groups/my_groups.html",
        {
            "request": request,
            "user": user,
            "memberships": memberships,
            "GroupStatus": models.GroupStatus,
            "now": datetime.utcnow(),
        },
    )
