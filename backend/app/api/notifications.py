from fastapi import APIRouter, Request

from app import clock
from app.auth import CurrentEmployee
from app.db import Db, EntityId
from app.schemas import NotificationOut, ReadAllResponse
from app.services import notifications

router = APIRouter(prefix="/api/notifications", tags=["Уведомления"])
LIST_LIMIT = 100


@router.get("", summary="Уведомления сотрудника, новые первыми", response_model=list[NotificationOut])
def list_notifications(request: Request, employee: CurrentEmployee, db: Db):
    # сгорание проверяется при чтении: бонус, до срока которого меньше двух суток, даёт уведомление здесь
    rules = request.app.state.store.content().rules
    notifications.notify_expiring_bonuses(db, employee.id, rules, clock.now())
    return notifications.list_for(db, employee.id, LIST_LIMIT)


@router.post("/read-all", summary="Отметить все уведомления прочитанными", response_model=ReadAllResponse)
def read_all(employee: CurrentEmployee, db: Db):
    return {"read": notifications.mark_all_read(db, employee.id, clock.now())}


@router.post(
    "/{notification_id}/read", summary="Отметить уведомление прочитанным", response_model=NotificationOut
)
def read_one(notification_id: EntityId, employee: CurrentEmployee, db: Db):
    return notifications.mark_read(db, employee.id, notification_id, clock.now())
