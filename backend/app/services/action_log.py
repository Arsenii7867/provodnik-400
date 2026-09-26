"""Журнал действий сотрудников: вход, выход, старт, выбор, истечение, отказ и завершение
прохождения с полезной нагрузкой. Пишется в одной транзакции с самим действием, поэтому
запись есть ровно тогда, когда действие состоялось."""

from app.models import ActionLog


def log(db, employee_id, action, entity_type, entity_id, payload, now):
    db.add(
        ActionLog(
            employee_id=employee_id,
            action=action,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            payload_json=payload or {},
            created_at=now,
        )
    )
