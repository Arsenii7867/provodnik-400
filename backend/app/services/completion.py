"""Итог прохождения и всё, что он запускает в той же транзакции: исход, очки и XP по
rules.yaml с прибавкой к профилю (finish_run даёт значения колонок scenario_runs), затем после
условного UPDATE владение компетенциями, достижения по правилам, переход уровня с уведомлением,
событие run_completed для LMS и запись в журнал действий (complete_run)."""

from sqlalchemy import func, select, update

from app import clock
from app.models import Employee, Profile, ScenarioRun
from app.scenarios import engine
from app.services import achievements, action_log, analytics, notifications, outbox, scoring


def finish_run(db, run, content, state, now):
    """Итог прохождения: исход, финальные шкалы, очки и XP по rules.yaml; XP сразу прибавляется
    к профилю, повтор сценария даёт долю очков."""
    role_complete = engine.role_chain_complete(state["role_chain"])
    breakdown = scoring.xp_breakdown(
        state["outcome"],
        state["loyalty"],
        state["safety"],
        state["timers_answered"],
        role_complete,
        content.rules,
    )
    score = scoring.score_of(breakdown)
    earlier = db.scalar(
        select(func.count())
        .select_from(ScenarioRun)
        .where(
            ScenarioRun.employee_id == run.employee_id,
            ScenarioRun.scenario_id == run.scenario_id,
            ScenarioRun.status == "finished",
        )
    )
    xp = scoring.xp_for(score, earlier > 0, content.rules)
    db.execute(
        update(Profile)
        .where(Profile.employee_id == run.employee_id)
        .values(xp_total=Profile.xp_total + xp, updated_at=now)
    )
    competencies = {
        code: {"earned": state["earned"].get(code, 0), "assessed": assessed}
        for code, assessed in state["assessed"].items()
    }
    return {
        "outcome": state["outcome"],
        "loyalty_final": state["loyalty"],
        "safety_final": state["safety"],
        "score": score,
        "xp_earned": xp,
        "xp_breakdown_json": breakdown,
        "competencies_json": competencies,
        "role_complete": role_complete,
        "finished_at": now,
    }


def complete_run(db, run, scenario, content, values, now):
    """Что замыкает цикл в той же транзакции после записи итога: владение компетенциями по
    окну прохождений, достижения по правилам, переход уровня с уведомлением, событие для LMS и
    запись в журнал действий."""
    employee = db.get(Employee, run.employee_id)
    mastery = analytics.refresh_competencies(db, content, employee.id, now)
    facts = {
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "outcome": values["outcome"],
        "service_class": run.service_class,
        "native_class": run.service_class == scenario["context"]["service_class"],
        "critical": bool(scenario.get("critical")),
        "role_complete": values["role_complete"],
        "timers_answered": values["timers_answered"],
        "expired_timers": values["expired_timers"],
        "loyalty": values["loyalty_final"],
        "safety": values["safety_final"],
    }
    outbox.emit(
        db,
        "run_completed",
        facts
        | {
            "employee_code": employee.code,
            "scenario_version": run.scenario_version,
            "score": values["score"],
            "xp": values["xp_earned"],
            "competencies": values["competencies_json"],
            "finished_at": clock.iso(now),
        },
        now,
    )
    awarded = achievements.evaluate(db, content, employee, facts, mastery, now)
    xp_after = db.scalar(select(Profile.xp_total).where(Profile.employee_id == employee.id))
    level_up = notify_level_up(db, content, employee, xp_after - values["xp_earned"], xp_after, now)
    payload = {
        "outcome": values["outcome"],
        "xp": values["xp_earned"],
        "score": values["score"],
        "achievements": [item["id"] for item in awarded],
        "level_up": level_up,
    }
    action_log.log(db, employee.id, "run_finished", "run", run.id, payload, now)


def notify_level_up(db, content, employee, xp_before, xp_after, now):
    """Уведомление и событие при смене уровня; возвращает id нового уровня или None."""
    before = scoring.level_for(xp_before, content.levels)
    after = scoring.level_for(xp_after, content.levels)
    if before["id"] == after["id"]:
        return None
    if after["next_threshold"] is None:
        body = f"Накоплено {xp_after} XP, это высший уровень."
    else:
        remaining = after["next_threshold"] - xp_after
        body = f"Накоплено {xp_after} XP. До уровня «{after['next_title']}» осталось {remaining} XP."
    notifications.create(
        db,
        employee.id,
        "level_up",
        f"Новый уровень: {after['title']}",
        body,
        {"level_id": after["id"], "xp_total": xp_after},
        f"level_up:{after['id']}:{employee.id}",
        now,
    )
    payload = {"employee_code": employee.code, "level_id": after["id"], "title": after["title"]}
    outbox.emit(db, "level_up", payload | {"xp_total": xp_after}, now)
    return after["id"]
