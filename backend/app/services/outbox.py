"""Исходящие события для HR и LMS: завершение прохождения, достижение, новый уровень. Событие
пишется в одной транзакции с тем, что его вызвало; интеграция читает события по курсору
after_id и подтверждает ack. Фоновой доставки нет, неподтверждённые события просто остаются."""

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


def fetch(db, after_id, limit):
    """События с id больше after_id по порядку; next_after_id это курсор для следующего запроса."""
    rows = db.scalars(
        select(OutboxEvent).where(OutboxEvent.id > after_id).order_by(OutboxEvent.id).limit(limit)
    ).all()
    return {"items": [view(row) for row in rows], "next_after_id": rows[-1].id if rows else after_id}


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
