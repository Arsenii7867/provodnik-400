from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app import clock
from app.auth import CurrentEmployee, require_role
from app.db import MAX_ID, Db
from app.errors import ApiError
from app.models import Brigade, Employee
from app.schemas import AnalyticsMeResponse, TeamAnalyticsResponse
from app.services import analytics, team_analytics

router = APIRouter(prefix="/api/analytics", tags=["Аналитика"])
Mentor = Annotated[Employee, Depends(require_role("mentor"))]
# границы как у id в пути: число больше int64 иначе даёт OverflowError драйвера и 500
BrigadeId = Annotated[int | None, Query(ge=1, le=MAX_ID)]


@router.get(
    "/me",
    summary="Личная аналитика: владение, проседающие, пробелы, рекомендации, темп, эскалация, динамика",
    response_model=AnalyticsMeResponse,
)
def me(request: Request, employee: CurrentEmployee, db: Db):
    return analytics.personal(db, request.app.state.store, employee, clock.now())


@router.get(
    "/team",
    summary="Аналитика бригады для наставника: проседающие по сотрудникам, средние по компетенциям",
    response_model=TeamAnalyticsResponse,
)
def team(request: Request, employee: Mentor, db: Db, brigade_id: BrigadeId = None):
    brigade = employee.brigade if brigade_id is None else db.get(Brigade, brigade_id)
    if brigade is None:
        raise ApiError(404, "brigade_not_found", "Бригады с таким номером нет")
    return team_analytics.team(db, request.app.state.store, brigade, clock.now())
