"""Уведомления сотруднику: достижение и новый уровень при завершении прохождения, позже новый
сценарий, челлендж и сгорающие баллы. У каждого повода свой dedupe_key с уникальностью в базе,
поэтому событие даёт ровно одно уведомление, сколько бы раз его ни создавали."""

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app import clock
from app.errors import ApiError
from app.models import Notification


def create(db, employee_id, kind, title, body, payload, dedupe_key, now):
    """Возвращает уведомление или None, если запись с таким dedupe_key уже есть."""
    row = Notification(
        employee_id=employee_id,
        kind=kind,
        title=title,
        body=body,
        payload_json=payload or {},
        dedupe_key=dedupe_key,
        created_at=now,
    )
    try:
        # точка сохранения: повтор ключа откатывает только эту вставку, а не весь ход сотрудника
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return None
    return row


def view(row):
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "payload": row.payload_json,
        "created_at": clock.iso(row.created_at),
        "read_at": clock.iso(row.read_at),
    }


def list_for(db, employee_id, limit):
    rows = db.scalars(
        select(Notification)
        .where(Notification.employee_id == employee_id)
        .order_by(Notification.id.desc())
        .limit(limit)
    ).all()
    return [view(row) for row in rows]


def mark_read(db, employee_id, notification_id, now):
    row = db.get(Notification, notification_id)
    if row is None or row.employee_id != employee_id:
        raise ApiError(404, "notification_not_found", "Такого уведомления нет")
    if row.read_at is None:
        row.read_at = now
        db.commit()
    return view(row)


def mark_all_read(db, employee_id, now):
    result = db.execute(
        update(Notification)
        .where(Notification.employee_id == employee_id, Notification.read_at.is_(None))
        .values(read_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount
