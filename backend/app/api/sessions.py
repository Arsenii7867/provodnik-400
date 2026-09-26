from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from app import clock
from app.auth import CurrentEmployee
from app.db import Db, EntityId
from app.schemas import ActiveResponse, ChooseRequest, ExpireRequest, RunState, StartSessionRequest
from app.services import session_service

router = APIRouter(prefix="/api/sessions", tags=["Прохождение"])


@router.post("", summary="Начать прохождение сценария", response_model=RunState, status_code=201)
def start(
    body: StartSessionRequest,
    request: Request,
    response: Response,
    employee: CurrentEmployee,
    db: Db,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
):
    store = request.app.state.store
    now = clock.now()
    run, created = session_service.start_run(
        db, store, employee, body.scenario_id, body.service_class, idempotency_key, now
    )
    if not created:
        response.status_code = 200
    return session_service.state_view(run, store, now)


@router.get("/active", summary="Активное прохождение сотрудника", response_model=ActiveResponse)
def active(request: Request, employee: CurrentEmployee, db: Db):
    store = request.app.state.store
    run = session_service.active_run(db, employee)
    return {"active": session_service.state_view(run, store, clock.now()) if run else None}


@router.get("/{run_id}", summary="Состояние прохождения", response_model=RunState)
def get_state(run_id: EntityId, request: Request, employee: CurrentEmployee, db: Db):
    run = session_service.get_run(db, employee, run_id)
    return session_service.state_view(run, request.app.state.store, clock.now())


@router.post("/{run_id}/choose", summary="Выбрать вариант в текущем узле", response_model=RunState)
def choose(run_id: EntityId, body: ChooseRequest, request: Request, employee: CurrentEmployee, db: Db):
    store = request.app.state.store
    grace = request.app.state.settings.timer_grace_seconds
    now = clock.now()
    run = session_service.get_run(db, employee, run_id)
    step = session_service.choose(db, store, run, body.option_id, body.step_no, now, grace)
    return session_service.state_view(run, store, now, step)


@router.post("/{run_id}/expire", summary="Сообщить об истечении таймера", response_model=RunState)
def expire(run_id: EntityId, body: ExpireRequest, request: Request, employee: CurrentEmployee, db: Db):
    store = request.app.state.store
    grace = request.app.state.settings.timer_grace_seconds
    now = clock.now()
    run = session_service.get_run(db, employee, run_id)
    step = session_service.expire(db, store, run, body.step_no, now, grace)
    return session_service.state_view(run, store, now, step)


@router.post("/{run_id}/abandon", summary="Прервать прохождение", response_model=RunState)
def abandon(run_id: EntityId, request: Request, employee: CurrentEmployee, db: Db):
    now = clock.now()
    run = session_service.get_run(db, employee, run_id)
    session_service.abandon(db, run, now)
    return session_service.state_view(run, request.app.state.store, now)
