"""
Background tasks — run via APScheduler.
Main job: expire timed-out join request steps and advance to next priority.
"""
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.services import notifications

logger = logging.getLogger(__name__)


def check_expired_steps() -> None:
    """Called by scheduler every minute. Expire steps past their deadline."""
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        expired_steps = (
            db.query(models.JoinRequestStep)
            .filter(
                models.JoinRequestStep.status == models.StepStatus.PENDING,
                models.JoinRequestStep.expires_at <= now,
            )
            .all()
        )
        for step in expired_steps:
            logger.info("Step %d expirou (join_request=%d)", step.id, step.join_request_id)
            step.status = models.StepStatus.EXPIRED
            step.responded_at = now
            db.commit()
            _advance_request(db, step.join_request)
    except Exception as exc:
        logger.error("Erro no check_expired_steps: %s", exc)
        db.rollback()
    finally:
        db.close()


def _advance_request(db: Session, join_request: models.JoinRequest) -> None:
    """Move join request to next priority step, or mark as rejected."""
    # Find next waiting step
    next_step = (
        db.query(models.JoinRequestStep)
        .filter(
            models.JoinRequestStep.join_request_id == join_request.id,
            models.JoinRequestStep.status == models.StepStatus.WAITING,
        )
        .order_by(models.JoinRequestStep.priority)
        .first()
    )

    current_steps = [s for s in join_request.steps if s.status in (
        models.StepStatus.EXPIRED, models.StepStatus.REJECTED
    )]

    if next_step:
        # Check if the target group still has space
        group = next_step.group
        if group.is_full or group.status == models.GroupStatus.CLOSED:
            next_step.status = models.StepStatus.SKIPPED
            db.commit()
            _advance_request(db, join_request)
            return

        join_request.current_step = next_step.priority
        db.commit()

        # notify the current step's requester that we moved on
        prev = [s for s in current_steps if s.status in (models.StepStatus.EXPIRED, models.StepStatus.REJECTED)]
        if prev:
            notifications.notify_requester_next_step(db, prev[-1], next_step)

        notifications.notify_leader_join_request(db, next_step)
    else:
        # All options exhausted
        join_request.status = models.RequestStatus.REJECTED
        join_request.resolved_at = datetime.utcnow()
        db.commit()
        notifications.notify_requester_rejected(db, join_request, "todas as opções foram esgotadas")


def process_step_response(db: Session, step: models.JoinRequestStep, accepted: bool) -> None:
    """Handle leader's accept/reject response."""
    now = datetime.utcnow()

    if step.status != models.StepStatus.PENDING:
        return  # already processed

    step.responded_at = now

    if accepted:
        group = step.group
        if group.is_full:
            # Group became full in the meantime — treat as rejected
            step.status = models.StepStatus.SKIPPED
            db.commit()
            _advance_request(db, step.join_request)
            return

        step.status = models.StepStatus.ACCEPTED
        join_request = step.join_request
        join_request.status = models.RequestStatus.ACCEPTED
        join_request.resolved_at = now

        # Mark remaining steps as skipped
        for s in join_request.steps:
            if s.id != step.id and s.status == models.StepStatus.WAITING:
                s.status = models.StepStatus.SKIPPED

        # Add member to group
        membership = models.GroupMember(
            group_id=group.id,
            user_id=join_request.requester_id,
            status=models.RequestStatus.ACCEPTED,
        )
        db.add(membership)

        # Consumir autorização avulsa do solicitante
        from app.deps import get_valid_authorization, consume_authorization
        requester = join_request.requester
        if requester.role != models.UserRole.ADMIN:
            auth = get_valid_authorization(db, requester)
            if auth:
                consume_authorization(db, auth)

        # Update group status if full
        if group.is_full:
            group.status = models.GroupStatus.FULL

        db.commit()

        notifications.notify_requester_accepted(db, step)
        notifications.notify_group_new_member(db, group, join_request.requester)
    else:
        step.status = models.StepStatus.REJECTED
        db.commit()
        _advance_request(db, step.join_request)
