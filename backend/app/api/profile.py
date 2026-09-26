from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import func, or_, select

from app import clock
from app.auth import CurrentEmployee, employee_view
from app.db import Db
from app.models import AchievementEarned, BonusPoint, Profile, ScenarioRun
from app.schemas import ProfileResponse, RunHistoryItem
from app.services import analytics, leaderboard, notifications, scoring

router = APIRouter(prefix="/api/profile", tags=["Профиль"])


def run_title(content, run):
    scenario = content.scenarios.get(run.scenario_id)
    return scenario["title"] if scenario else run.scenario_id


def last_run_view(content, run):
    if run is None:
        return None
    return {
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "title": run_title(content, run),
        "outcome": run.outcome,
        "xp": run.xp_earned,
        "score": run.score,
        "finished_at": clock.iso(run.finished_at),
    }


def bonus_view(db, employee_id, rules, now):
    """Действующие бонусы челленджей и те из них, что сгорают в ближайшие часы из rules.yaml."""
    active = or_(BonusPoint.expires_at.is_(None), BonusPoint.expires_at > now)
    query = select(BonusPoint).where(BonusPoint.employee_id == employee_id, active)
    rows = db.scalars(query.order_by(BonusPoint.expires_at)).all()
    horizon = now + timedelta(hours=rules["bonus"]["expiring_notice_hours"])
    expiring = [row for row in rows if row.expires_at is not None and row.expires_at <= horizon]
    return {
        "active_total": sum(row.points for row in rows),
        "expiring": [
            {"points": row.points, "reason": row.reason, "expires_at": clock.iso(row.expires_at)}
            for row in expiring
        ],
    }


@router.get(
    "",
    summary="Профиль: уровень, XP, компетенции, достижения, место в бригаде",
    response_model=ProfileResponse,
)
def profile(request: Request, employee: CurrentEmployee, db: Db):
    content = request.app.state.store.content()
    now = clock.now()
    notifications.notify_expiring_bonuses(db, employee.id, content.rules, now)
    xp_total = db.get(Profile, employee.id).xp_total
    level = scoring.level_for(xp_total, content.levels)
    finished = ScenarioRun.employee_id == employee.id, ScenarioRun.status == "finished"
    runs_count = db.scalar(select(func.count()).select_from(ScenarioRun).where(*finished))
    last_run = db.scalar(select(ScenarioRun).where(*finished).order_by(ScenarioRun.id.desc()).limit(1))
    mine = AchievementEarned.employee_id == employee.id
    earned = db.scalars(select(AchievementEarned.achievement_id).where(mine))
    # достижение, убранное из YAML, в счётчик не входит: каталог его тоже не показывает
    known = {item["id"] for item in content.achievements}
    achievements_count = sum(achievement_id in known for achievement_id in earned)
    return employee_view(employee) | {
        "xp_total": xp_total,
        "level": level,
        "xp_to_next": level["next_threshold"] - xp_total if level["next_threshold"] is not None else None,
        "competencies": analytics.competency_rows(db, content, employee.id),
        "achievements_count": achievements_count,
        "achievements_total": len(content.achievements),
        "runs_count": runs_count,
        "rank_brigade": leaderboard.rank_in_brigade(db, employee, now),
        "last_run": last_run_view(content, last_run),
        "bonus": bonus_view(db, employee.id, content.rules, now),
    }


@router.get(
    "/runs", summary="История прохождений сотрудника, новые первыми", response_model=list[RunHistoryItem]
)
def runs(request: Request, employee: CurrentEmployee, db: Db):
    content = request.app.state.store.content()
    rows = db.scalars(
        select(ScenarioRun).where(ScenarioRun.employee_id == employee.id).order_by(ScenarioRun.id.desc())
    ).all()
    return [
        {
            "run_id": run.id,
            "scenario_id": run.scenario_id,
            "title": run_title(content, run),
            "status": run.status,
            "outcome": run.outcome,
            "loyalty_final": run.loyalty_final,
            "safety_final": run.safety_final,
            "score": run.score,
            "xp": run.xp_earned,
            "started_at": clock.iso(run.started_at),
            "finished_at": clock.iso(run.finished_at),
            "expired_timers": run.expired_timers,
            "service_class": run.service_class,
        }
        for run in rows
    ]
