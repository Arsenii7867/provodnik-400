"""Интеграция с HR и LMS по заголовку X-API-Key: результаты сотрудника, экспорт завершённых
прохождений с курсором, события outbox с курсором и подтверждением, журнал действий, справочник
компетенций и создание сотрудника внешней системой. Логика короткая и живёт здесь."""

import secrets
import string
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import auth, clock
from app.auth import employee_view, require_api_key
from app.db import MAX_ID, Db
from app.errors import ApiError
from app.models import AchievementEarned, ActionLog, Brigade, Employee, Profile, ScenarioRun
from app.schemas import (
    AckResponse,
    ActionsPage,
    CompetencyRef,
    CreatedEmployeeOut,
    EmployeeResultsOut,
    EventsPage,
    ResultsPage,
)
from app.services import action_log, analytics, outbox, scoring

router = APIRouter(prefix="/api/integration", tags=["Интеграция"], dependencies=[Depends(require_api_key)])
PIN_LENGTH = 4
Limit = Annotated[int, Query(ge=1, le=500)]
Cursor = Annotated[int, Query(ge=0, le=MAX_ID)]


class AckRequest(BaseModel):
    ids: list[Annotated[int, Field(ge=1, le=MAX_ID)]] = Field(min_length=1, max_length=500)


class CreateEmployeeRequest(BaseModel):
    employee_code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    brigade: str = Field(min_length=1, max_length=64)
    role: Literal["conductor", "mentor"] = "conductor"


def employee_or_404(db, code):
    employee = db.scalar(select(Employee).where(Employee.code == code))
    if employee is None:
        raise ApiError(404, "employee_not_found", "Сотрудника с таким кодом нет")
    return employee


def run_item(run, employee_code, brigade):
    return {
        "run_id": run.id,
        "employee_code": employee_code,
        "brigade": brigade,
        "scenario_id": run.scenario_id,
        "scenario_version": run.scenario_version,
        "finished_at": clock.iso(run.finished_at),
        "outcome": run.outcome,
        "loyalty_final": run.loyalty_final,
        "safety_final": run.safety_final,
        "score": run.score,
        "xp": run.xp_earned,
        "competencies": run.competencies_json or {},
    }


@router.get(
    "/employees/{code}/results",
    summary="Результаты сотрудника: уровень, владение, прохождения, достижения",
    response_model=EmployeeResultsOut,
)
def employee_results(code: str, request: Request, db: Db):
    employee = employee_or_404(db, code)
    content = request.app.state.store.content()
    xp_total = db.scalar(select(Profile.xp_total).where(Profile.employee_id == employee.id)) or 0
    runs = analytics.finished_runs(db, employee.id)
    earned = db.scalars(
        select(AchievementEarned)
        .where(AchievementEarned.employee_id == employee.id)
        .order_by(AchievementEarned.id)
    ).all()
    return employee_view(employee) | {
        "xp_total": xp_total,
        "level": scoring.level_for(xp_total, content.levels),
        "competencies": [
            {
                "code": item["code"],
                "mastery": item["mastery"],
                "status": item["status"],
                "runs_assessed": item["runs_assessed"],
            }
            for item in analytics.mastery_for(db, content, employee.id)
        ],
        "runs": [run_item(run, employee.code, employee.brigade.name) for run in reversed(runs)],
        "achievements": [{"id": row.achievement_id, "earned_at": clock.iso(row.earned_at)} for row in earned],
    }


@router.get("/results", summary="Экспорт завершённых прохождений с курсором", response_model=ResultsPage)
def results(db: Db, since: datetime | None = None, limit: Limit = 100, cursor: Cursor = 0):
    query = (
        select(ScenarioRun, Employee.code, Brigade.name)
        .join(Employee, Employee.id == ScenarioRun.employee_id)
        .join(Brigade, Brigade.id == Employee.brigade_id)
        .where(ScenarioRun.status == "finished", ScenarioRun.id > cursor)
    )
    if since is not None:
        query = query.where(ScenarioRun.finished_at >= since)
    rows = db.execute(query.order_by(ScenarioRun.id).limit(limit)).all()
    return {
        "items": [run_item(run, code, brigade) for run, code, brigade in rows],
        # курсор отдаётся, только если страница полная: иначе клиент зря сделает ещё один запрос
        "next_cursor": rows[-1][0].id if len(rows) == limit else None,
    }


@router.get("/events", summary="События для LMS с курсором after_id", response_model=EventsPage)
def events(db: Db, after_id: Cursor = 0, limit: Limit = 100):
    return outbox.fetch(db, after_id, limit)


@router.post("/events/ack", summary="Подтвердить доставку событий", response_model=AckResponse)
def ack(body: AckRequest, db: Db):
    return {"acked": outbox.ack(db, body.ids, clock.now())}


@router.get("/competencies", summary="Справочник компетенций", response_model=list[CompetencyRef])
def competencies(request: Request):
    content = request.app.state.store.content()
    return [
        {"code": item["code"], "title": item["title"], "description": item.get("description", "")}
        for item in content.competencies
    ]


@router.get(
    "/employees/{code}/actions",
    summary="Журнал действий сотрудника с курсором after_id",
    response_model=ActionsPage,
)
def actions(code: str, db: Db, after_id: Cursor = 0, limit: Limit = 100):
    employee = employee_or_404(db, code)
    rows = db.scalars(
        select(ActionLog)
        .where(ActionLog.employee_id == employee.id, ActionLog.id > after_id)
        .order_by(ActionLog.id)
        .limit(limit)
    ).all()
    items = [
        {
            "id": row.id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "payload": row.payload_json,
            "created_at": clock.iso(row.created_at),
        }
        for row in rows
    ]
    return {"items": items, "next_after_id": rows[-1].id if rows else after_id}


@router.post(
    "/employees",
    summary="Создать сотрудника из HR-системы; PIN возвращается один раз",
    response_model=CreatedEmployeeOut,
    status_code=201,
)
def create_employee(body: CreateEmployeeRequest, response: Response, db: Db):
    if db.scalar(select(Employee).where(Employee.code == body.employee_code)) is not None:
        raise ApiError(409, "employee_exists", "Сотрудник с таким кодом уже есть")
    brigade = db.scalar(select(Brigade).where(Brigade.name == body.brigade))
    if brigade is None:
        raise ApiError(404, "brigade_not_found", "Бригады с таким названием нет")
    now = clock.now()
    pin = "".join(secrets.choice(string.digits) for _ in range(PIN_LENGTH))
    salt = auth.new_salt()
    employee = Employee(
        code=body.employee_code,
        display_name=body.display_name,
        role=body.role,
        brigade_id=brigade.id,
        pin_hash=auth.hash_pin(pin, salt),
        pin_salt=salt,
        is_synthetic=False,
        created_at=now,
    )
    db.add(employee)
    db.flush()
    db.add(Profile(employee_id=employee.id, xp_total=0, updated_at=now))
    payload = {"employee_code": employee.code, "brigade": brigade.name, "role": employee.role}
    outbox.emit(db, "employee_created", payload | {"created_at": clock.iso(now)}, now)
    action_log.log(
        db, employee.id, "employee_created", "employee", employee.code, {"source": "integration"}, now
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return employee_view(employee) | {"pin": pin}
