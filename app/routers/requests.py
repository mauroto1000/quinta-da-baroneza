from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.deps import get_current_user
from app.services import notifications, tasks as task_service

router = APIRouter(prefix="/requests", tags=["requests"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/new/{slot_id}", response_class=HTMLResponse)
def new_request_page(slot_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    slot = db.query(models.TeeSlot).filter(models.TeeSlot.id == slot_id).first()
    if not slot:
        return RedirectResponse("/schedule", status_code=302)

    # Groups in this slot with available spots, excluding user's own group
    groups = (
        db.query(models.Group)
        .filter(
            models.Group.tee_slot_id == slot_id,
            models.Group.status.in_([
                models.GroupStatus.OPEN,
                models.GroupStatus.MIXED,
            ]),
        )
        .all()
    )
    available_groups = [
        g for g in groups
        if not g.is_full
        and not any(m.user_id == user.id and m.status == models.RequestStatus.ACCEPTED for m in g.members)
    ]

    return templates.TemplateResponse(
        "requests/new.html",
        {
            "request": request,
            "user": user,
            "slot": slot,
            "available_groups": available_groups,
            "error": None,
            "GroupStatus": models.GroupStatus,
        },
    )


@router.post("/new/{slot_id}", response_class=HTMLResponse)
def submit_request(
    slot_id: int,
    request: Request,
    priority_1: int = Form(0),
    priority_2: int = Form(0),
    priority_3: int = Form(0),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    slot = db.query(models.TeeSlot).filter(models.TeeSlot.id == slot_id).first()
    if not slot:
        return RedirectResponse("/schedule", status_code=302)

    selected_ids = [gid for gid in [priority_1, priority_2, priority_3] if gid]

    # Validate: at least 1, no duplicates
    if not selected_ids:
        groups = _get_available_groups(db, slot_id, user.id)
        return templates.TemplateResponse(
            "requests/new.html",
            {"request": request, "user": user, "slot": slot, "available_groups": groups,
             "error": "Selecione ao menos um grupo.", "GroupStatus": models.GroupStatus},
        )

    if len(selected_ids) != len(set(selected_ids)):
        groups = _get_available_groups(db, slot_id, user.id)
        return templates.TemplateResponse(
            "requests/new.html",
            {"request": request, "user": user, "slot": slot, "available_groups": groups,
             "error": "Não selecione o mesmo grupo mais de uma vez.", "GroupStatus": models.GroupStatus},
        )

    # Verify all groups belong to this slot and are available
    for gid in selected_ids:
        g = db.query(models.Group).filter(models.Group.id == gid, models.Group.tee_slot_id == slot_id).first()
        if not g:
            groups = _get_available_groups(db, slot_id, user.id)
            return templates.TemplateResponse(
                "requests/new.html",
                {"request": request, "user": user, "slot": slot, "available_groups": groups,
                 "error": "Grupo inválido selecionado.", "GroupStatus": models.GroupStatus},
            )

    # Check user not already in slot
    existing_membership = (
        db.query(models.GroupMember)
        .join(models.Group)
        .filter(
            models.Group.tee_slot_id == slot_id,
            models.GroupMember.user_id == user.id,
            models.GroupMember.status == models.RequestStatus.ACCEPTED,
        )
        .first()
    )
    if existing_membership:
        return RedirectResponse(f"/schedule/day/{slot.slot_datetime.date().isoformat()}", status_code=302)

    # Check for existing pending request for this slot
    existing_request = (
        db.query(models.JoinRequest)
        .join(models.JoinRequestStep)
        .join(models.Group)
        .filter(
            models.JoinRequest.requester_id == user.id,
            models.JoinRequest.status == models.RequestStatus.PENDING,
            models.Group.tee_slot_id == slot_id,
        )
        .first()
    )
    if existing_request:
        groups = _get_available_groups(db, slot_id, user.id)
        return templates.TemplateResponse(
            "requests/new.html",
            {"request": request, "user": user, "slot": slot, "available_groups": groups,
             "error": "Você já tem uma solicitação pendente para este horário.", "GroupStatus": models.GroupStatus},
        )

    # Create join request
    join_request = models.JoinRequest(requester_id=user.id, current_step=1)
    db.add(join_request)
    db.flush()

    first_group_id = selected_ids[0]
    first_group = db.query(models.Group).filter(models.Group.id == first_group_id).first()

    # If first group is OPEN — immediate join, no approval needed
    if first_group.status == models.GroupStatus.OPEN and not first_group.is_full:
        membership = models.GroupMember(
            group_id=first_group_id,
            user_id=user.id,
            status=models.RequestStatus.ACCEPTED,
        )
        db.add(membership)
        join_request.status = models.RequestStatus.ACCEPTED
        join_request.resolved_at = datetime.utcnow()

        step = models.JoinRequestStep(
            join_request_id=join_request.id,
            group_id=first_group_id,
            priority=1,
            status=models.StepStatus.ACCEPTED,
            notified_at=datetime.utcnow(),
            responded_at=datetime.utcnow(),
        )
        db.add(step)
        if first_group.is_full:
            first_group.status = models.GroupStatus.FULL
        db.commit()
        notifications.notify_group_new_member(db, first_group, user)
        return RedirectResponse(f"/groups/{first_group_id}", status_code=302)

    # Create steps
    for i, gid in enumerate(selected_ids, start=1):
        step_status = models.StepStatus.WAITING if i > 1 else models.StepStatus.WAITING
        step = models.JoinRequestStep(
            join_request_id=join_request.id,
            group_id=gid,
            priority=i,
            status=models.StepStatus.WAITING,
        )
        db.add(step)
    db.flush()

    db.commit()
    db.refresh(join_request)

    # Notify first group leader
    first_step = next(s for s in join_request.steps if s.priority == 1)
    notifications.notify_leader_join_request(db, first_step)

    return RedirectResponse("/requests/my", status_code=302)


def _get_available_groups(db: Session, slot_id: int, user_id: int):
    groups = (
        db.query(models.Group)
        .filter(
            models.Group.tee_slot_id == slot_id,
            models.Group.status.in_([models.GroupStatus.OPEN, models.GroupStatus.MIXED]),
        )
        .all()
    )
    return [
        g for g in groups
        if not g.is_full
        and not any(m.user_id == user_id and m.status == models.RequestStatus.ACCEPTED for m in g.members)
    ]


@router.get("/my", response_class=HTMLResponse)
def my_requests(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    join_requests = (
        db.query(models.JoinRequest)
        .filter(models.JoinRequest.requester_id == user.id)
        .order_by(models.JoinRequest.created_at.desc())
        .limit(30)
        .all()
    )

    return templates.TemplateResponse(
        "requests/my_requests.html",
        {
            "request": request,
            "user": user,
            "join_requests": join_requests,
            "RequestStatus": models.RequestStatus,
            "StepStatus": models.StepStatus,
        },
    )


@router.get("/respond/{token}/{action}", response_class=HTMLResponse)
def respond_to_request(token: str, action: str, request: Request, db: Session = Depends(get_db)):
    """Leader responds via WhatsApp link (no login required — token auth)."""
    step = db.query(models.JoinRequestStep).filter(
        models.JoinRequestStep.response_token == token
    ).first()

    if not step:
        return templates.TemplateResponse(
            "requests/respond_result.html",
            {"request": request, "user": None, "message": "Link inválido ou expirado.", "success": False},
        )

    if step.status != models.StepStatus.PENDING:
        return templates.TemplateResponse(
            "requests/respond_result.html",
            {"request": request, "user": None,
             "message": "Esta solicitação já foi respondida ou expirou.", "success": False},
        )

    if step.expires_at and step.expires_at < datetime.utcnow():
        return templates.TemplateResponse(
            "requests/respond_result.html",
            {"request": request, "user": None, "message": "O prazo para resposta expirou.", "success": False},
        )

    accepted = action.lower() == "accept"
    task_service.process_step_response(db, step, accepted)

    msg = "Entrada *aceita* com sucesso! O jogador foi notificado." if accepted else "Entrada recusada. O jogador será notificado."
    return templates.TemplateResponse(
        "requests/respond_result.html",
        {"request": request, "user": None, "message": msg, "success": accepted},
    )


@router.post("/step/{step_id}/respond", response_class=HTMLResponse)
def respond_step_in_app(
    step_id: int,
    request: Request,
    action: str = Form(...),
    db: Session = Depends(get_db),
):
    """Leader responds from within the app (requires login)."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    step = db.query(models.JoinRequestStep).filter(models.JoinRequestStep.id == step_id).first()
    if not step or step.group.leader_id != user.id:
        return RedirectResponse("/schedule", status_code=302)

    accepted = action.lower() == "accept"
    task_service.process_step_response(db, step, accepted)

    return RedirectResponse(f"/groups/{step.group_id}", status_code=302)


@router.post("/{request_id}/cancel", response_class=HTMLResponse)
def cancel_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    join_request = db.query(models.JoinRequest).filter(
        models.JoinRequest.id == request_id,
        models.JoinRequest.requester_id == user.id,
    ).first()

    if join_request and join_request.status == models.RequestStatus.PENDING:
        join_request.status = models.RequestStatus.CANCELLED
        join_request.resolved_at = datetime.utcnow()
        for step in join_request.steps:
            if step.status in (models.StepStatus.PENDING, models.StepStatus.WAITING):
                step.status = models.StepStatus.SKIPPED
        db.commit()

    return RedirectResponse("/requests/my", status_code=302)
