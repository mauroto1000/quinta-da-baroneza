"""
Auto-geração de TeeSlots para um determinado dia com base nas configurações padrão.
Chamado ao visualizar a agenda — garante que os slots existam sem intervenção do admin.
"""
from datetime import datetime, timedelta, date, time
from sqlalchemy.orm import Session
from app import models
from app.deps import get_system_config


def ensure_slots_for_date(db: Session, day: date) -> None:
    """Cria ScheduleBlock e TeeSlots padrão para o dia, se ainda não existirem."""
    start_str = get_system_config(db, "default_start_time", "07:00")
    end_str = get_system_config(db, "default_end_time", "17:00")
    interval = int(get_system_config(db, "tee_interval_minutes", "10"))
    tees_str = get_system_config(db, "default_tees", "1,10")

    try:
        start_time = time.fromisoformat(start_str)
        end_time = time.fromisoformat(end_str)
    except ValueError:
        start_time = time(7, 0)
        end_time = time(17, 0)

    tees = []
    for t in tees_str.split(","):
        t = t.strip()
        if t in ("1", "10"):
            tees.append(models.TeeNumber(t))

    if not tees:
        tees = [models.TeeNumber.TEE_1, models.TeeNumber.TEE_10]

    for tee in tees:
        # Verifica se já existe bloco para este dia/tee
        block = db.query(models.ScheduleBlock).filter(
            models.ScheduleBlock.date == day,
            models.ScheduleBlock.tee_number == tee,
        ).first()

        if not block:
            block = models.ScheduleBlock(
                date=day,
                tee_number=tee,
                start_time=start_time,
                end_time=end_time,
                interval_minutes=interval,
                is_blocked=False,
            )
            db.add(block)
            db.flush()

        # Gera slots faltantes (sem apagar os existentes)
        if not block.is_blocked:
            _fill_slots(db, block)

    db.commit()


def _fill_slots(db: Session, block: models.ScheduleBlock) -> None:
    current = datetime.combine(block.date, block.start_time)
    end = datetime.combine(block.date, block.end_time)
    while current <= end:
        exists = db.query(models.TeeSlot).filter(
            models.TeeSlot.slot_datetime == current,
            models.TeeSlot.tee_number == block.tee_number,
        ).first()
        if not exists:
            db.add(models.TeeSlot(
                schedule_block_id=block.id,
                slot_datetime=current,
                tee_number=block.tee_number,
            ))
        current += timedelta(minutes=block.interval_minutes)


def ensure_slots_for_window(db: Session, days: int) -> None:
    """Garante slots para os próximos N dias."""
    today = date.today()
    for i in range(days + 1):
        ensure_slots_for_date(db, today + timedelta(days=i))
