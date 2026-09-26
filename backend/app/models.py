"""Таблицы тренажёра (SQLAlchemy 2.0, Mapped). База хранит людей и прогресс; сценарии, правила
и справочники живут в YAML. Все столбцы времени через UtcDateTime: в базу уходит naive UTC,
наружу приходит aware UTC, чтобы сравнения с clock.now() вели себя одинаково в SQLite и PostgreSQL."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # время без зоны считается UTC (так PyYAML отдаёт даты справочников), а не местным временем машины
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UtcDateTime, dict: JSON, list: JSON}


class Depot(Base):
    __tablename__ = "depots"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class Brigade(Base):
    __tablename__ = "brigades"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    depot_id: Mapped[int] = mapped_column(ForeignKey("depots.id"))
    depot: Mapped[Depot] = relationship()


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    role: Mapped[str]
    brigade_id: Mapped[int] = mapped_column(ForeignKey("brigades.id"))
    pin_hash: Mapped[str]
    pin_salt: Mapped[str]
    is_synthetic: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime]
    brigade: Mapped[Brigade] = relationship()


class Profile(Base):
    __tablename__ = "profiles"

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), primary_key=True)
    xp_total: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime]


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime]


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"
    __table_args__ = (
        UniqueConstraint("employee_id", "idempotency_key"),
        Index("ix_scenario_runs_employee_scenario_status", "employee_id", "scenario_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    scenario_id: Mapped[str]
    scenario_version: Mapped[int]
    service_class: Mapped[str]
    status: Mapped[str]
    current_node: Mapped[str]
    step_no: Mapped[int]
    state_json: Mapped[dict]
    node_entered_at: Mapped[datetime]
    deadline_at: Mapped[datetime | None]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    outcome: Mapped[str | None]
    loyalty_final: Mapped[int | None]
    safety_final: Mapped[int | None]
    score: Mapped[int | None]
    xp_earned: Mapped[int | None]
    xp_breakdown_json: Mapped[dict | None]
    competencies_json: Mapped[dict | None]
    expired_timers: Mapped[int] = mapped_column(default=0)
    timers_answered: Mapped[int] = mapped_column(default=0)
    role_complete: Mapped[bool] = mapped_column(default=False)
    idempotency_key: Mapped[str | None]


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "step_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scenario_runs.id"))
    step_no: Mapped[int]
    node_id: Mapped[str]
    node_text: Mapped[str]
    option_id: Mapped[str | None]
    option_text: Mapped[str | None]
    expired: Mapped[bool]
    loyalty_before: Mapped[int]
    safety_before: Mapped[int]
    loyalty_after: Mapped[int]
    safety_after: Mapped[int]
    effects_json: Mapped[dict]
    competencies_json: Mapped[dict]
    delayed_applied_json: Mapped[list]
    role_step: Mapped[str | None]
    escalation_target: Mapped[str | None]
    verdict: Mapped[str | None]
    answered_in_seconds: Mapped[float | None]
    created_at: Mapped[datetime]


class EmployeeCompetency(Base):
    __tablename__ = "employee_competencies"

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), primary_key=True)
    competency: Mapped[str] = mapped_column(primary_key=True)
    earned_sum: Mapped[int]
    assessed_sum: Mapped[int]
    runs_assessed: Mapped[int]
    mastery: Mapped[float | None]
    status: Mapped[str]
    updated_at: Mapped[datetime]


class AchievementEarned(Base):
    __tablename__ = "achievements_earned"
    __table_args__ = (UniqueConstraint("employee_id", "achievement_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    achievement_id: Mapped[str]
    run_id: Mapped[int | None] = mapped_column(ForeignKey("scenario_runs.id"))
    earned_at: Mapped[datetime]


class BonusPoint(Base):
    __tablename__ = "bonus_points"
    __table_args__ = (UniqueConstraint("employee_id", "challenge_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    points: Mapped[int]
    reason: Mapped[str]
    challenge_id: Mapped[str | None]
    earned_at: Mapped[datetime]
    expires_at: Mapped[datetime | None]


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    description: Mapped[str]
    scenario_ids_json: Mapped[list]
    condition_json: Mapped[dict]
    bonus_points: Mapped[int]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    created_at: Mapped[datetime]


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_employee_read", "employee_id", "read_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    kind: Mapped[str]
    title: Mapped[str]
    body: Mapped[str]
    payload_json: Mapped[dict]
    dedupe_key: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime]
    read_at: Mapped[datetime | None]


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str]
    payload_json: Mapped[dict]
    created_at: Mapped[datetime]
    delivered_at: Mapped[datetime | None]


class ActionLog(Base):
    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    payload_json: Mapped[dict]
    created_at: Mapped[datetime]
