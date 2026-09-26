from fastapi import APIRouter, Request
from sqlalchemy import select

from app import clock
from app.auth import CurrentEmployee
from app.db import Db
from app.models import AchievementEarned
from app.schemas import AchievementOut

router = APIRouter(prefix="/api/achievements", tags=["Достижения"])


@router.get("", summary="Каталог достижений с признаком получения", response_model=list[AchievementOut])
def catalog(request: Request, employee: CurrentEmployee, db: Db):
    content = request.app.state.store.content()
    rows = db.scalars(select(AchievementEarned).where(AchievementEarned.employee_id == employee.id)).all()
    earned_at = {row.achievement_id: row.earned_at for row in rows}
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "description": item["description"],
            "rule_text": item["rule_text"],
            "rule_type": item["rule"]["type"],
            "earned": item["id"] in earned_at,
            "earned_at": clock.iso(earned_at.get(item["id"])),
        }
        for item in content.achievements
    ]
