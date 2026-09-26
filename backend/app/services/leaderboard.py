"""Рейтинг для лидерборда: сумма лучших очков по каждому сценарию плюс неистёкшие бонусы
челленджей. Считается запросом на каждое обращение и нигде не хранится; истёкшие бонусы просто
не попадают в сумму, так баллы сгорают без фоновых задач. Профиль берёт отсюда место в
бригаде, лидерборд ранжирует те же строки по выбранному охвату."""

from sqlalchemy import func, or_, select

from app.models import AchievementEarned, BonusPoint, Employee, ScenarioRun


def ratings(db, employee_ids, now):
    """Словарь employee_id -> best_scores_sum, bonus_points, achievements, score для перечисленных."""
    ids = list(employee_ids)
    result = {
        employee_id: {"best_scores_sum": 0, "bonus_points": 0, "achievements": 0, "score": 0}
        for employee_id in ids
    }
    if not ids:
        return result
    best = (
        select(ScenarioRun.employee_id, func.max(ScenarioRun.score).label("best"))
        .where(ScenarioRun.employee_id.in_(ids), ScenarioRun.status == "finished")
        .group_by(ScenarioRun.employee_id, ScenarioRun.scenario_id)
        .subquery()
    )
    sums = select(best.c.employee_id, func.sum(best.c.best)).group_by(best.c.employee_id)
    for employee_id, total in db.execute(sums):
        result[employee_id]["best_scores_sum"] = int(total)
    active = or_(BonusPoint.expires_at.is_(None), BonusPoint.expires_at > now)
    bonuses = (
        select(BonusPoint.employee_id, func.sum(BonusPoint.points))
        .where(BonusPoint.employee_id.in_(ids), active)
        .group_by(BonusPoint.employee_id)
    )
    for employee_id, total in db.execute(bonuses):
        result[employee_id]["bonus_points"] = int(total)
    counts = (
        select(AchievementEarned.employee_id, func.count())
        .where(AchievementEarned.employee_id.in_(ids))
        .group_by(AchievementEarned.employee_id)
    )
    for employee_id, count in db.execute(counts):
        result[employee_id]["achievements"] = count
    for row in result.values():
        row["score"] = row["best_scores_sum"] + row["bonus_points"]
    return result


def ranked(db, employees, now):
    """Строки рейтинга с местом: по очкам, затем по числу достижений, затем по коду сотрудника."""
    scores = ratings(db, [employee.id for employee in employees], now)
    rows = [{"employee": employee, **scores[employee.id]} for employee in employees]
    rows.sort(key=lambda row: (-row["score"], -row["achievements"], row["employee"].code))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def rank_in_brigade(db, employee, now):
    """Место проводника среди проводников своей бригады; наставники в рейтинге не участвуют."""
    if employee.role != "conductor":
        return None
    members = db.scalars(
        select(Employee).where(Employee.brigade_id == employee.brigade_id, Employee.role == "conductor")
    ).all()
    return next(row["rank"] for row in ranked(db, members, now) if row["employee"].id == employee.id)
