"""Сборка исторического разбора и версионированные снимки, без зависимости от HTTP/ContentStore."""

from copy import deepcopy

from sqlalchemy import func, select

from app import clock
from app.models import AchievementEarned, BonusPoint, RunStep, ScenarioRun
from app.scenarios import engine, refs
from app.schemas import DebriefResponse
from app.services import analytics, scoring

SNAPSHOT_VERSION = 1


def snapshot_data(envelope):
    if (
        isinstance(envelope, dict)
        and type(envelope.get("version")) is int
        and envelope["version"] == SNAPSHOT_VERSION
    ):
        data = envelope.get("data")
        return data if isinstance(data, dict) else None
    return None


def action_source(scenario, node_id, option_id, expired):
    node = (scenario.get("nodes") or {}).get(node_id) or {}
    if expired:
        return (node.get("timer") or {}).get("on_expire") or {}
    if node.get("type") == "event":
        return node
    return next((option for option in node.get("options") or [] if option["id"] == option_id), {})


def capture_teaching(scenario, content, step):
    node = scenario["nodes"].get(step["node_id"]) or {}
    source = action_source(scenario, step["node_id"], step["option_id"], step["expired"])
    explanation = source.get("debrief") or {}
    verdict = "expired" if step["expired"] else explanation.get("verdict")
    data = {
        "passenger_says": node.get("passenger_says"),
        "why": explanation.get("why"),
        "better": explanation.get("better"),
        "best_option": best_option(node, verdict),
        "refs": refs.describe_many(content.refs, explanation.get("refs") or []),
    }
    return {"version": SNAPSHOT_VERSION, "data": deepcopy(data)}


def capture_response(db, content, scenario, run):
    data = DebriefResponse.model_validate(render(db, content, scenario, run)).model_dump(mode="json")
    return {"version": SNAPSHOT_VERSION, "data": data}


def verdict_of(option):
    return (option.get("debrief") or {}).get("verdict")


def best_option(node, verdict):
    """Лучший вариант узла для строки «как лучше»; у лучшего хода и у события подсказки нет."""
    if verdict == "best" or node.get("type") != "dialog":
        return None
    options = [item for item in node.get("options") or [] if verdict_of(item) == "best"]
    # безусловный лучший вариант был доступен на любом пути; условный в этом прохождении мог быть скрыт
    unconditional = [item for item in options if not item.get("when")]
    chosen = unconditional or options
    return {"id": chosen[0]["id"], "text": chosen[0]["text"]} if chosen else None


def step_view(scenario, content, engine_steps, row):
    node = scenario["nodes"].get(row.node_id) or {}
    source = action_source(scenario, row.node_id, row.option_id, row.expired)
    debrief = source.get("debrief") or {}
    teaching = snapshot_data((engine_steps.get(row.step_no) or {}).get("teaching_snapshot"))
    historical = teaching is not None
    teaching = (
        teaching
        if historical
        else {
            "passenger_says": node.get("passenger_says"),
            "why": debrief.get("why"),
            "better": debrief.get("better"),
            "best_option": best_option(node, row.verdict),
            "refs": refs.describe_many(content.refs, debrief.get("refs") or []),
        }
    )
    return {
        "history_status": "snapshot" if historical else "legacy",
        "step_no": row.step_no,
        "node_id": row.node_id,
        "node_text": row.node_text,
        "passenger_says": teaching.get("passenger_says"),
        "option_id": row.option_id,
        "option_text": row.option_text,
        "expired": row.expired,
        "timer_seconds": (engine_steps.get(row.step_no) or {}).get("timer_seconds"),
        "answered_in_seconds": row.answered_in_seconds,
        "verdict": row.verdict,
        "why": teaching.get("why"),
        "better": teaching.get("better"),
        "best_option": teaching.get("best_option"),
        "refs": teaching.get("refs"),
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


def challenges_completed(db, content, run):
    """Челленджи, бонус за которые начислен этим прохождением; название из текущего YAML."""
    rows = db.scalars(select(BonusPoint).where(BonusPoint.run_id == run.id).order_by(BonusPoint.id)).all()
    titles = {item["id"]: item["title"] for item in content.challenges}
    return [
        {
            "id": row.challenge_id,
            "title": titles.get(row.challenge_id, row.reason),
            "bonus_points": row.points,
            "bonus_expires_at": clock.iso(row.expires_at),
        }
        for row in rows
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


def render(db, content, scenario, run):
    state = run.state_json
    rows = db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.step_no)).all()
    engine_steps = {step["step_no"]: step for step in state["steps"]}
    same_scenario, _ = earlier_runs(db, run, same_scenario=True)
    _, xp_before = earlier_runs(db, run, same_scenario=False)
    captured = sum(snapshot_data(step.get("teaching_snapshot")) is not None for step in state["steps"])
    history_status = "snapshot" if rows and captured == len(rows) else "partial" if captured else "legacy"
    return {
        "history_status": history_status,
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "title": scenario.get("title", run.scenario_id),
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
        "challenges_completed": challenges_completed(db, content, run),
        "competencies_delta": competencies_delta(db, content, run),
        "level_before": scoring.level_for(xp_before, content.levels),
        "level_after": scoring.level_for(xp_before + run.xp_earned, content.levels),
    }
