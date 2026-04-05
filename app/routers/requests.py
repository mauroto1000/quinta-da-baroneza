from datetime import datetime, date
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.deps import get_current_user, get_valid_authorization, consume_authorization
from app.services import notifications, tasks as task_service

router = APIRouter(prefix="/requests", tags=["requests"])
templates = Jinja2Templates(directory="app/templates")


def _available_groups_on_date(db: Session, day: date, user_id: int, exclude_group_id: int = 0):
    """Grupos disponíveis no mesmo dia, excluindo o grupo já escolhido e grupos onde o usuário já é membro."""
    slots = (
        db.query(models.TeeSlot)
        .join(models.ScheduleBlock)
        .filter(models.ScheduleBlock.date == day)
        .all()
    )
    slot_ids = [s.id for s in slots]

    groups = (
        db.query(models.Group)
        .filter(
            models.Group.tee_slot_id.in_(slot_ids),
            models.Group.status.in_([models.GroupStatus.OPEN, models.GroupStatus.MIXED]),
            models.Group.id != exclude_group_id,
        )
        .all()
    )
    return [
        g for g in groups
        if not g.is_full
        and not any(m.user_id == user_id and m.status == models.RequestStatus.ACCEPTED for m in g.members)
    ]


@router.get("/new/{group_id}", response_class=HTMLResponse)
def new_request_page(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    first_group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not first_group:
        return RedirectResponse("/schedule", status_code=302)

    slot = first_group.tee_slot
    day = slot.slot_datetime.date()

    other_groups = _available_groups_on_date(db, day, user.id, exclude_group_id=group_id)

    return templates.TemplateResponse(
        "requests/new.html",
        {
            "request": request,
            "user": user,
            "first_group": first_group,
            "slot": slot,
            "other_groups": other_groups,
            "day": day,
            "error": None,
            "GroupStatus": models.GroupStatus,
        },
    )


@router.post("/new/{group_id}", response_class=HTMLResponse)
def submit_request(
    group_id: int,
    request: Request,
    priority_2: int = Form(0),
    priority_3: int = Form(0),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    first_group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not first_group:
        return RedirectResponse("/schedule", status_code=302)

    slot = first_group.tee_slot
    day = slot.slot_datetime.date()

    def render_error(msg):
        other_groups = _available_groups_on_date(db, day, user.id, exclude_group_id=group_id)
        return templates.TemplateResponse(
            "requests/new.html",
            {
                "request": request, "user": user,
                "first_group": first_group, "slot": slot,
                "other_groups": other_groups, "day": day,
                "error": msg, "GroupStatus": models.GroupStatus,
            },
        )

    # Build ordered list: priority 1 is always first_group
    selected_ids = [group_id] + [gid for gid in [priority_2, priority_3] if gid]

    if len(selected_ids) != len(set(selected_ids)):
        return render_error("Não selecione o mesmo grupo mais de uma vez.")

    # Validate priorities 2 and 3
    for gid in selected_ids[1:]:
        g = db.query(models.Group).filter(models.Group.id == gid).first()
        if not g:
            return render_error("Grupo inválido selecionado.")

    # Verificar autorização (admins estão sempre autorizados)
    if user.role != models.UserRole.ADMIN:
        auth = get_valid_authorization(db, user)
        if not auth:
            return render_error("Você não possui autorização de agendamento. Procure a secretaria do clube.")

    # Check user not already in a group on this day
    existing_membership = (
        db.query(models.GroupMember)
        .join(models.Group)
        .join(models.TeeSlot)
        .join(models.ScheduleBlock)
        .filter(
            models.ScheduleBlock.date == day,
            models.GroupMember.user_id == user.id,
            models.GroupMember.status == models.RequestStatus.ACCEPTED,
        )
        .first()
    )
    if existing_membership:
        return render_error("Você já está em um grupo neste dia.")

    # Check for existing pending request on this day
    existing_request = (
        db.query(models.JoinRequest)
        .join(models.JoinRequestStep)
        .join(models.Group)
        .join(models.TeeSlot)
        .join(models.ScheduleBlock)
        .filter(
            models.JoinRequest.requester_id == user.id,
            models.JoinRequest.status == models.RequestStatus.PENDING,
            models.ScheduleBlock.date == day,
        )
        .first()
    )
    if existing_request:
        return render_error("Você já tem uma solicitação pendente para este dia.")

    # Create join request
    join_request = models.JoinRequest(requester_id=user.id, current_step=1)
    db.add(join_request)
    db.flush()

    first_g = db.query(models.Group).filter(models.Group.id == group_id).first()

    # If first group is OPEN — immediate join
    if first_g.status == models.GroupStatus.OPEN and not first_g.is_full:
        membership = models.GroupMember(
            group_id=group_id,
            user_id=user.id,
            status=models.RequestStatus.ACCEPTED,
        )
        db.add(membership)
        join_request.status = models.RequestStatus.ACCEPTED
        join_request.resolved_at = datetime.utcnow()
        step = models.JoinRequestStep(
            join_request_id=join_request.id,
            group_id=group_id,
            priority=1,
            status=models.StepStatus.ACCEPTED,
            notified_at=datetime.utcnow(),
            responded_at=datetime.utcnow(),
        )
        db.add(step)
        if first_g.is_full:
            first_g.status = models.GroupStatus.FULL
        db.commit()
        notifications.notify_group_new_member(db, first_g, user)
        return RedirectResponse(f"/groups/{group_id}", status_code=302)

    # Create steps
    for i, gid in enumerate(selected_ids, start=1):
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

    msg = "Entrada aceita com sucesso! O jogador foi notificado." if accepted else "Entrada recusada. O jogador será notificado."
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
