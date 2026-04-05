from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, DateTime,
    ForeignKey, Enum, Text, UniqueConstraint, Date, Time
)
from sqlalchemy.orm import relationship
from app.database import Base


class UserRole(str, PyEnum):
    PLAYER = "player"
    ADMIN = "admin"


class AuthorizationType(str, PyEnum):
    SINGLE = "single"        # um agendamento, consumida ao usar
    PERMANENT = "permanent"  # sócio ou autorização irrestrita


class GroupStatus(str, PyEnum):
    OPEN = "open"        # qualquer um entra sem aprovação
    MIXED = "mixed"      # responsável aprova, mas aceita desconhecidos
    CLOSED = "closed"    # responsável aprova; grupo pode estar fechado
    FULL = "full"        # grupo completo


class RequestStatus(str, PyEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class StepStatus(str, PyEnum):
    WAITING = "waiting"   # aguardando etapas anteriores
    PENDING = "pending"   # notificação enviada, aguardando resposta
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"   # timeout atingido
    SKIPPED = "skipped"   # grupo ficou cheio ou indisponível antes de chegar aqui


class TeeNumber(str, PyEnum):
    TEE_1 = "1"
    TEE_10 = "10"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    whatsapp = Column(String(20), nullable=False)
    hcp_index = Column(Float, nullable=True)
    password_hash = Column(String(128), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.PLAYER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    led_groups = relationship("Group", foreign_keys="Group.leader_id", back_populates="leader")
    memberships = relationship("GroupMember", back_populates="user")
    join_requests = relationship("JoinRequest", back_populates="requester")


# ---------------------------------------------------------------------------
# Schedule — one record per (date, tee) block configured by admin
# ---------------------------------------------------------------------------
class ScheduleBlock(Base):
    __tablename__ = "schedule_blocks"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    tee_number = Column(Enum(TeeNumber), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    interval_minutes = Column(Integer, default=10, nullable=False)
    is_blocked = Column(Boolean, default=False)
    block_reason = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("date", "tee_number", name="uq_schedule_date_tee"),)

    tee_slots = relationship("TeeSlot", back_populates="schedule_block", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# TeeSlot — each individual tee time (date + time + tee)
# ---------------------------------------------------------------------------
class TeeSlot(Base):
    __tablename__ = "tee_slots"

    id = Column(Integer, primary_key=True, index=True)
    schedule_block_id = Column(Integer, ForeignKey("schedule_blocks.id"), nullable=False)
    slot_datetime = Column(DateTime, nullable=False, index=True)
    tee_number = Column(Enum(TeeNumber), nullable=False)
    is_blocked = Column(Boolean, default=False)
    block_reason = Column(String(200), nullable=True)

    __table_args__ = (UniqueConstraint("slot_datetime", "tee_number", name="uq_slot_datetime_tee"),)

    schedule_block = relationship("ScheduleBlock", back_populates="tee_slots")
    groups = relationship("Group", back_populates="tee_slot")


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    tee_slot_id = Column(Integer, ForeignKey("tee_slots.id"), nullable=False)
    leader_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(GroupStatus), default=GroupStatus.MIXED, nullable=False)
    max_players = Column(Integer, default=4, nullable=False)
    notes = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tee_slot = relationship("TeeSlot", back_populates="groups")
    leader = relationship("User", foreign_keys=[leader_id], back_populates="led_groups")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    join_request_steps = relationship("JoinRequestStep", back_populates="group")

    @property
    def current_size(self):
        return sum(1 for m in self.members if m.status == RequestStatus.ACCEPTED)

    @property
    def available_spots(self):
        return self.max_players - self.current_size

    @property
    def is_full(self):
        return self.available_spots <= 0


# ---------------------------------------------------------------------------
# GroupMember
# ---------------------------------------------------------------------------
class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.ACCEPTED, nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    group = relationship("Group", back_populates="members")
    user = relationship("User", back_populates="memberships")


# ---------------------------------------------------------------------------
# JoinRequest — solicitação de um jogador para entrar em até 3 grupos
# ---------------------------------------------------------------------------
class JoinRequest(Base):
    __tablename__ = "join_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING, nullable=False)
    current_step = Column(Integer, default=1)  # 1, 2 or 3
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    requester = relationship("User", back_populates="join_requests")
    steps = relationship(
        "JoinRequestStep",
        back_populates="join_request",
        order_by="JoinRequestStep.priority",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# JoinRequestStep — cada tentativa (prioridade 1, 2, 3)
# ---------------------------------------------------------------------------
class JoinRequestStep(Base):
    __tablename__ = "join_request_steps"

    id = Column(Integer, primary_key=True, index=True)
    join_request_id = Column(Integer, ForeignKey("join_requests.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    priority = Column(Integer, nullable=False)  # 1, 2, 3
    status = Column(Enum(StepStatus), default=StepStatus.WAITING, nullable=False)
    notified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    response_token = Column(String(64), unique=True, nullable=True, index=True)

    join_request = relationship("JoinRequest", back_populates="steps")
    group = relationship("Group", back_populates="join_request_steps")


# ---------------------------------------------------------------------------
# SystemConfig — key/value store for runtime settings
# ---------------------------------------------------------------------------
class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String(80), primary_key=True)
    value = Column(String(500), nullable=False)
    description = Column(String(300), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)


# ---------------------------------------------------------------------------
# BookingAuthorization — controla quem pode agendar
# ---------------------------------------------------------------------------
class BookingAuthorization(Base):
    __tablename__ = "booking_authorizations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    auth_type = Column(Enum(AuthorizationType), nullable=False)
    notes = Column(String(300), nullable=True)       # ex: "Green fee pago em 05/04/2026"
    is_active = Column(Boolean, default=True, nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)     # None = sem expiração
    used_at = Column(DateTime, nullable=True)        # preenchido ao consumir (single)

    user = relationship("User", foreign_keys=[user_id], backref="authorizations")
    admin = relationship("User", foreign_keys=[granted_by])

    @property
    def is_valid(self) -> bool:
        if not self.is_active:
            return False
        if self.auth_type == AuthorizationType.SINGLE and self.used_at:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True


DEFAULT_CONFIGS = {
    "booking_window_days": ("14", "Dias de antecedência para agendamento"),
    "request_timeout_hours": ("1", "Horas para o responsável responder à solicitação"),
    "cancel_deadline_hours": ("24", "Horas mínimas de antecedência para cancelamento"),
    "max_groups_per_slot": ("6", "Número máximo de grupos por horário"),
    "evolution_api_url": ("", "URL da Evolution API (WhatsApp)"),
    "evolution_api_key": ("", "Chave da Evolution API"),
    "evolution_instance": ("", "Nome da instância na Evolution API"),
    "club_name": ("Quinta da Baroneza Golfe Clube", "Nome do clube"),
    "app_base_url": ("", "URL base da aplicação (ex: https://meusite.pythonanywhere.com)"),
    "default_start_time": ("07:00", "Horário padrão de início das saídas (HH:MM)"),
    "default_end_time": ("17:00", "Horário padrão de término das saídas (HH:MM)"),
    "default_tees": ("1,10", "Tees ativos por padrão (1, 10 ou 1,10)"),
    "tee_interval_minutes": ("10", "Intervalo padrão entre saídas (minutos)"),
}
