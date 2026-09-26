from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app import clock
from app.auth import CurrentEmployee
from app.db import Db
from app.schemas import LeaderboardResponse
from app.services import leaderboard

router = APIRouter(prefix="/api/leaderboard", tags=["Лидерборд"])


@router.get(
    "",
    summary="Рейтинг проводников по бригаде, депо или компании со своей строкой",
    response_model=LeaderboardResponse,
)
def board(
    employee: CurrentEmployee,
    db: Db,
    scope: Literal["brigade", "depot", "company"] = "brigade",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return leaderboard.board(db, employee, scope, limit, clock.now())
