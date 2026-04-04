"""
High-level notification helpers — compose messages and call whatsapp.send_whatsapp.
"""
import secrets
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app import models
from app.deps import get_system_config
from app.services.whatsapp import send_whatsapp


def _base_url(db: Session) -> str:
    return get_system_config(db, "app_base_url", "").rstrip("/")


def _club(db: Session) -> str:
    return get_system_config(db, "club_name", "Quinta da Baroneza")


def _timeout_hours(db: Session) -> int:
    return int(get_system_config(db, "request_timeout_hours", "1"))


# ---------------------------------------------------------------------------
# Notify group leader — new join request step
# ---------------------------------------------------------------------------
def notify_leader_join_request(db: Session, step: models.JoinRequestStep) -> None:
    group = step.group
    leader = group.leader
    requester = step.join_request.requester
    slot = group.tee_slot

    token = secrets.token_urlsafe(32)
    step.response_token = token
    step.notified_at = datetime.utcnow()
    step.expires_at = datetime.utcnow() + timedelta(hours=_timeout_hours(db))
    step.status = models.StepStatus.PENDING
    db.commit()

    base = _base_url(db)
    accept_url = f"{base}/requests/respond/{token}/accept"
    reject_url = f"{base}/requests/respond/{token}/reject"

    slot_fmt = slot.slot_datetime.strftime("%d/%m/%Y às %H:%M")
    tee_label = f"Tee #{slot.tee_number}"

    msg = (
        f"*{_club(db)}* — Solicitação de entrada no seu grupo\n\n"
        f"Olá, *{leader.full_name}*!\n\n"
        f"*{requester.full_name}* (HCP: {requester.hcp_index or 'N/I'}) solicita "
        f"entrar no seu grupo para:\n"
        f"📅 {slot_fmt} | {tee_label}\n\n"
        f"Você tem *{_timeout_hours(db)}h* para responder.\n\n"
        f"✅ Aceitar: {accept_url}\n"
        f"❌ Recusar: {reject_url}\n\n"
        f"_(Ou acesse o app e responda pela plataforma)_"
    )
    send_whatsapp(db, leader.whatsapp, msg)


# ---------------------------------------------------------------------------
# Notify requester — accepted
# ---------------------------------------------------------------------------
def notify_requester_accepted(db: Session, step: models.JoinRequestStep) -> None:
    requester = step.join_request.requester
    group = step.group
    slot = group.tee_slot
    slot_fmt = slot.slot_datetime.strftime("%d/%m/%Y às %H:%M")
    tee_label = f"Tee #{slot.tee_number}"

    msg = (
        f"*{_club(db)}* — Entrada confirmada! 🎉\n\n"
        f"Olá, *{requester.full_name}*!\n\n"
        f"Sua solicitação foi *aceita* pelo responsável do grupo.\n\n"
        f"📅 {slot_fmt} | {tee_label}\n"
        f"👤 Responsável: {group.leader.full_name}\n\n"
        f"Boa bola! ⛳"
    )
    send_whatsapp(db, requester.whatsapp, msg)


# ---------------------------------------------------------------------------
# Notify requester — rejected or all options exhausted
# ---------------------------------------------------------------------------
def notify_requester_rejected(db: Session, join_request: models.JoinRequest, reason: str = "") -> None:
    requester = join_request.requester
    base = _base_url(db)

    msg = (
        f"*{_club(db)}* — Solicitação não aceita\n\n"
        f"Olá, *{requester.full_name}*!\n\n"
        f"Infelizmente sua solicitação de entrada em grupo não pôde ser atendida"
        + (f" ({reason})" if reason else "") + ".\n\n"
        f"Acesse o app para tentar novamente ou criar um novo grupo:\n{base}"
    )
    send_whatsapp(db, requester.whatsapp, msg)


# ---------------------------------------------------------------------------
# Notify requester — moved to next priority
# ---------------------------------------------------------------------------
def notify_requester_next_step(db: Session, step: models.JoinRequestStep, next_step: models.JoinRequestStep) -> None:
    requester = step.join_request.requester
    msg = (
        f"*{_club(db)}* — Atualização da sua solicitação\n\n"
        f"Olá, *{requester.full_name}*!\n\n"
        f"O responsável do grupo de prioridade {step.priority} recusou sua entrada. "
        f"Sua solicitação foi encaminhada para o grupo de prioridade {next_step.priority}.\n\n"
        f"Aguarde a resposta. ⏳"
    )
    send_whatsapp(db, requester.whatsapp, msg)


# ---------------------------------------------------------------------------
# Notify group members — someone joined
# ---------------------------------------------------------------------------
def notify_group_new_member(db: Session, group: models.Group, new_user: models.User) -> None:
    slot = group.tee_slot
    slot_fmt = slot.slot_datetime.strftime("%d/%m/%Y às %H:%M")
    for member in group.members:
        if member.status != models.RequestStatus.ACCEPTED:
            continue
        if member.user_id == new_user.id:
            continue
        msg = (
            f"*{_club(db)}* — Novo membro no seu grupo\n\n"
            f"Olá, *{member.user.full_name}*!\n\n"
            f"*{new_user.full_name}* entrou no seu grupo para "
            f"📅 {slot_fmt} | Tee #{slot.tee_number}.\n\n"
            f"Boa bola! ⛳"
        )
        send_whatsapp(db, member.user.whatsapp, msg)


# ---------------------------------------------------------------------------
# Notify group members — cancellation
# ---------------------------------------------------------------------------
def notify_group_member_cancelled(db: Session, group: models.Group, cancelled_user: models.User) -> None:
    slot = group.tee_slot
    slot_fmt = slot.slot_datetime.strftime("%d/%m/%Y às %H:%M")
    for member in group.members:
        if member.status != models.RequestStatus.ACCEPTED:
            continue
        if member.user_id == cancelled_user.id:
            continue
        msg = (
            f"*{_club(db)}* — Saída do grupo\n\n"
            f"Olá, *{member.user.full_name}*!\n\n"
            f"*{cancelled_user.full_name}* cancelou sua participação no grupo para "
            f"📅 {slot_fmt} | Tee #{slot.tee_number}.\n\n"
            f"Há uma vaga disponível no grupo agora."
        )
        send_whatsapp(db, member.user.whatsapp, msg)
