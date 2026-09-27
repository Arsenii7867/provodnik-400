"""Исходящие события для HR и LMS: завершение прохождения, достижение, новый уровень. Событие
пишется в одной транзакции с тем, что его вызвало; интеграция читает неподтверждённые события
и подтверждает ack, архив доступен по after_id. Фоновой доставки нет."""

from sqlalchemy import select, update

from app import clock
from app.models import OutboxEvent


def emit(db, event_type, payload, now):
    event = OutboxEvent(event_type=event_type, payload_json=payload, created_at=now)
    db.add(event)
    return event


def view(row):
    return {
        "id": row.id,
        "event_type": row.event_type,
        "payload": row.payload_json,
        "created_at": clock.iso(row.created_at),
        "delivered_at": clock.iso(row.delivered_at),
    }


def fetch(db, after_id, limit, pending_only=False):
    """Архив по курсору или неподтверждённые события, включая поздние commit с меньшим id."""
    query = select(OutboxEvent)
    if pending_only:
        query = query.where(OutboxEvent.delivered_at.is_(None))
    else:
        query = query.where(OutboxEvent.id > after_id)
    rows = db.scalars(query.order_by(OutboxEvent.id).limit(limit)).all()
    next_after_id = 0 if pending_only else (rows[-1].id if rows else after_id)
    return {"items": [view(row) for row in rows], "next_after_id": next_after_id}


def ack(db, ids, now):
    """Помечает события доставленными; возвращает, сколько записей были ещё не подтверждены."""
    result = db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id.in_(list(ids)), OutboxEvent.delivered_at.is_(None))
        .values(delivered_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount
