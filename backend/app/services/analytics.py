"""Аналитика компетенций по данным прохождений: окно последних завершённых прохождений
сотрудника для подсчёта владения (формулы в scoring.py, числа в rules.yaml) и пересчёт таблицы
employee_competencies при завершении прохождения. Личная и командная аналитика читают эти же
функции, ничего заранее не хранится кроме самой таблицы."""

from sqlalchemy import select

from app.models import EmployeeCompetency, ScenarioRun
from app.services import scoring


def competency_runs(db, employee_id, max_run_id=None):
    """Завершённые прохождения от нового к старому в форме для scoring.mastery_by_competency;
    max_run_id ограничивает историю прохождениями с id не больше указанного (владение «до» и
    «после» конкретного прохождения в разборе)."""
    query = select(ScenarioRun.scenario_id, ScenarioRun.competencies_json).where(
        ScenarioRun.employee_id == employee_id, ScenarioRun.status == "finished"
    )
    if max_run_id is not None:
        query = query.where(ScenarioRun.id <= max_run_id)
    rows = db.execute(query.order_by(ScenarioRun.id.desc())).all()
    return [
        {
            "scenario_id": scenario_id,
            "earned": {code: item["earned"] for code, item in (competencies or {}).items()},
            "assessed": {code: item["assessed"] for code, item in (competencies or {}).items()},
        }
        for scenario_id, competencies in rows
    ]


def mastery_for(db, content, employee_id, max_run_id=None):
    codes = [item["code"] for item in content.competencies]
    return scoring.mastery_by_competency(competency_runs(db, employee_id, max_run_id), codes, content.rules)


def refresh_competencies(db, content, employee_id, now):
    """Пересчитывает строки employee_competencies по окну и возвращает владение по компетенциям."""
    mastery = mastery_for(db, content, employee_id)
    query = select(EmployeeCompetency).where(EmployeeCompetency.employee_id == employee_id)
    rows = {row.competency: row for row in db.scalars(query)}
    for item in mastery:
        row = rows.get(item["code"])
        if row is None:
            row = EmployeeCompetency(employee_id=employee_id, competency=item["code"])
            db.add(row)
        row.earned_sum = item["earned"]
        row.assessed_sum = item["assessed"]
        row.runs_assessed = item["runs_assessed"]
        row.mastery = item["mastery"]
        row.status = item["status"]
        row.updated_at = now
    return mastery


def competency_rows(db, content, employee_id):
    """Компетенции для профиля: строки таблицы, а для ещё не оценённых кодов пробел с нулями."""
    query = select(EmployeeCompetency).where(EmployeeCompetency.employee_id == employee_id)
    rows = {row.competency: row for row in db.scalars(query)}
    result = []
    for item in content.competencies:
        row = rows.get(item["code"])
        result.append(
            {
                "code": item["code"],
                "title": item["title"],
                "mastery": row.mastery if row else None,
                "status": row.status if row else "gap",
                "earned": row.earned_sum if row else 0,
                "assessed": row.assessed_sum if row else 0,
                "runs_assessed": row.runs_assessed if row else 0,
            }
        )
    return result
