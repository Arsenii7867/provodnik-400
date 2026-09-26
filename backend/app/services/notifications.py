"""Уведомления сотруднику: достижение и новый уровень при завершении прохождения, челлендж
при активации и выполнении, новый сценарий после перечитывания контента, сгорающие баллы при
чтении. У каждого повода свой dedupe_key с уникальностью в базе, поэтому событие даёт ровно одно
уведомление, сколько бы раз его ни создавали."""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app import clock
from app.errors import ApiError
from app.models import BonusPoint, Employee, Notification
from app.services.texts import plural


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


def notify_expiring_bonuses(db, employee_id, rules, now):
    """Ленивое предупреждение о сгорании: при чтении уведомлений, профиля или челленджей каждый
    ещё действующий бонус, до срока которого меньше expiring_notice_hours, даёт одно уведомление.
    Уже сгоревшие бонусы уведомления не создают. Возвращает число новых записей."""
    horizon = now + timedelta(hours=rules["bonus"]["expiring_notice_hours"])
    soon = BonusPoint.expires_at > now, BonusPoint.expires_at <= horizon
    rows = db.scalars(
        select(BonusPoint).where(BonusPoint.employee_id == employee_id, *soon).order_by(BonusPoint.expires_at)
    ).all()
    created = 0
    for row in rows:
        hours = max(1, round((row.expires_at - now).total_seconds() / 3600))
        points = plural(row.points, "балл", "балла", "баллов")
        body = f"Через {plural(hours, 'час', 'часа', 'часов')} сгорают {points} к рейтингу: {row.reason}."
        payload = {"bonus_id": row.id, "points": row.points, "expires_at": clock.iso(row.expires_at)}
        key = f"points_expiring:{row.id}"
        if create(db, employee_id, "points_expiring", f"Сгорают {points}", body, payload, key, now):
            created += 1
    if created:
        db.commit()
    return created


def notify_new_scenarios(db, content, scenario_ids, now):
    """Уведомление всем сотрудникам о сценариях, появившихся после перечитывания контента."""
    employee_ids = db.scalars(select(Employee.id).order_by(Employee.id)).all()
    created = 0
    for scenario_id in scenario_ids:
        scenario = content.scenarios.get(scenario_id)
        if scenario is None:
            continue
        for employee_id in employee_ids:
            row = create(
                db,
                employee_id,
                "new_scenario",
                f"Новый сценарий: {scenario['title']}",
                scenario["summary"],
                {"scenario_id": scenario_id},
                f"new_scenario:{scenario_id}:{employee_id}",
                now,
            )
            created += row is not None
    return created
