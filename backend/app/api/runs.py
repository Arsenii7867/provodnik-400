"""Разбор завершённого прохождения покадрово: по каждому шагу шкалы до и после, вердикт, почему,
как лучше и цитаты норм из refs.yaml; исход, раскладка XP, новые достижения, дельты владения
компетенциями и уровень до и после. Снимки текстов узла и варианта берутся из run_steps,
тексты why, better и refs из текущего файла сценария."""

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.auth import CurrentEmployee
from app.db import Db, EntityId
from app.errors import ApiError
from app.models import AchievementEarned, RunStep, ScenarioRun
from app.scenarios import engine, refs
from app.schemas import DebriefResponse
from app.services import analytics, scoring, session_service

router = APIRouter(prefix="/api/runs", tags=["Разбор"])


def verdict_of(option):
    return (option.get("debrief") or {}).get("verdict")


def best_option(node, row):
    """Лучший вариант узла для строки «как лучше»; у лучшего хода и у события подсказки нет."""
    if row.verdict == "best" or node.get("type") != "dialog":
        return None
    options = [item for item in node.get("options") or [] if verdict_of(item) == "best"]
    # безусловный лучший вариант был доступен на любом пути; условный в этом прохождении мог быть скрыт
    unconditional = [item for item in options if not item.get("when")]
    chosen = unconditional or options
    return {"id": chosen[0]["id"], "text": chosen[0]["text"]} if chosen else None


def step_view(scenario, content, engine_steps, row):
    node = scenario["nodes"].get(row.node_id) or {}
    source = session_service.action_source(scenario, row.node_id, row.option_id, row.expired)
    debrief = source.get("debrief") or {}
    return {
        "step_no": row.step_no,
        "node_id": row.node_id,
        "node_text": row.node_text,
        "passenger_says": node.get("passenger_says"),
        "option_id": row.option_id,
        "option_text": row.option_text,
        "expired": row.expired,
        "timer_seconds": (engine_steps.get(row.step_no) or {}).get("timer_seconds"),
        "answered_in_seconds": row.answered_in_seconds,
        "verdict": row.verdict,
        "why": debrief.get("why"),
        "better": debrief.get("better"),
        "best_option": best_option(node, row),
        "refs": refs.describe_many(content.refs, debrief.get("refs") or []),
        "loyalty_before": row.loyalty_before,
        "loyalty_after": row.loyalty_after,
        "safety_before": row.safety_before,
        "safety_after": row.safety_after,
        "effects": row.effects_json,
        "competencies": row.competencies_json,
        "delayed_applied": [
            {"text": item["text"], "effects": item["effects"], "cancelled": item["cancelled"]}
            for item in row.delayed_applied_json
        ],
        "role_step": row.role_step,
        "escalation_target": row.escalation_target,
    }


def ending_view(content, node_id, node):
    debrief = node.get("debrief") or {}
    return {
        "id": node_id,
        "title": node.get("title", ""),
        "text": node.get("text", ""),
        "summary": debrief.get("summary", ""),
        "refs": refs.describe_many(content.refs, debrief.get("refs") or []),
    }


def achievements_new(db, content, run):
    ids = db.scalars(select(AchievementEarned.achievement_id).where(AchievementEarned.run_id == run.id)).all()
    by_id = {item["id"]: item for item in content.achievements}
    return [
        {
            "id": key,
            "title": by_id[key]["title"] if key in by_id else key,
            "description": by_id[key]["description"] if key in by_id else "",
        }
        for key in ids
    ]


def competencies_delta(db, content, run):
    """Владение до и после этого прохождения по окну: до считается по прохождениям с меньшим id."""
    before = {item["code"]: item for item in analytics.mastery_for(db, content, run.employee_id, run.id - 1)}
    after = {item["code"]: item for item in analytics.mastery_for(db, content, run.employee_id, run.id)}
    titles = {item["code"]: item["title"] for item in content.competencies}
    return [
        {
            "code": code,
            "title": titles.get(code, code),
            "earned": item["earned"],
            "assessed": item["assessed"],
            "mastery_before": before[code]["mastery"],
            "mastery_after": after[code]["mastery"],
            "status": after[code]["status"],
        }
        for code, item in (run.competencies_json or {}).items()
        if code in after
    ]


def earlier_runs(db, run, same_scenario):
    """Число завершённых прохождений сотрудника до этого; xp_total профиля это сумма их XP."""
    query = select(func.count(), func.coalesce(func.sum(ScenarioRun.xp_earned), 0)).where(
        ScenarioRun.employee_id == run.employee_id,
        ScenarioRun.status == "finished",
        ScenarioRun.id < run.id,
    )
    if same_scenario:
        query = query.where(ScenarioRun.scenario_id == run.scenario_id)
    return db.execute(query).one()


@router.get(
    "/{run_id}/debrief",
    summary="Разбор завершённого прохождения по шагам",
    response_model=DebriefResponse,
)
def debrief(run_id: EntityId, request: Request, employee: CurrentEmployee, db: Db):
    run = session_service.get_run(db, employee, run_id)
    if run.status != "finished":
        message = "Разбор доступен после завершения прохождения"
        raise ApiError(409, "run_not_finished", message, {"status": run.status})
    content = request.app.state.store.content()
    scenario = content.scenarios.get(run.scenario_id)
    if scenario is None:
        raise ApiError(404, "scenario_not_found", "Сценарий этого прохождения убран из каталога")
    state = session_service.deserialize_state(run.state_json)
    rows = db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.step_no)).all()
    engine_steps = {step["step_no"]: step for step in state["steps"]}
    same_scenario, _ = earlier_runs(db, run, same_scenario=True)
    _, xp_before = earlier_runs(db, run, same_scenario=False)
    return {
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "title": scenario["title"],
        "service_class": run.service_class,
        "outcome": run.outcome,
        "loyalty_start": rows[0].loyalty_before,
        "safety_start": rows[0].safety_before,
        "loyalty_final": run.loyalty_final,
        "safety_final": run.safety_final,
        "xp": run.xp_earned,
        "xp_breakdown": run.xp_breakdown_json,
        "score": run.score,
        "is_repeat": same_scenario > 0,
        "expired_timers": run.expired_timers,
        "timers_answered": run.timers_answered,
        "role_chain": engine.role_chain_progress(state),
        "steps": [step_view(scenario, content, engine_steps, row) for row in rows],
        "ending": ending_view(content, state["node"], scenario["nodes"].get(state["node"]) or {}),
        "achievements_new": achievements_new(db, content, run),
        "competencies_delta": competencies_delta(db, content, run),
        "level_before": scoring.level_for(xp_before, content.levels),
        "level_after": scoring.level_for(xp_before + run.xp_earned, content.levels),
    }
