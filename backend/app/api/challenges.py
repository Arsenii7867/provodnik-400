from fastapi import APIRouter, Request

from app import clock
from app.auth import CurrentEmployee
from app.db import Db
from app.schemas import ChallengeOut
from app.services import challenges, notifications

router = APIRouter(prefix="/api/challenges", tags=["Челленджи"])


@router.get(
    "",
    summary="Челленджи с прогрессом, окном и сроком сгорания бонуса",
    response_model=list[ChallengeOut],
)
def list_challenges(request: Request, employee: CurrentEmployee, db: Db):
    content = request.app.state.store.content()
    now = clock.now()
    notifications.notify_expiring_bonuses(db, employee.id, content.rules, now)
    return challenges.list_for(db, content, employee, now)
