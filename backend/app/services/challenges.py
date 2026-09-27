"""Челленджи по content/challenges.yaml: проверка формы справочника для загрузчика, активация
окна (строка таблицы challenges при сиде и при перечитывании контента, уведомление всем
сотрудникам), прогресс по завершённым прохождениям внутри окна и бонус за выполнение: запись
bonus_points со сроком сгорания, уведомление и событие для LMS. Условия декларативные, их типы
в реестре CONDITIONS; числа (баллы, дни, срок сгорания) приходят из YAML."""

from datetime import timedelta

from sqlalchemy import select

from app import clock
from app.models import BonusPoint, Challenge, Employee, ScenarioRun
from app.scenarios.engine import OUTCOMES
from app.services import notifications, outbox
from app.services.texts import date_words, plural

TEXT_FIELDS = ("id", "title", "description")
COUNT_FIELDS = ("bonus_points", "duration_days")


def condition_no_incident_all(runs, scenario_ids, params):
    done = {run.scenario_id for run in runs if run.outcome != "incident"}
    return len(done & set(scenario_ids)), len(scenario_ids)


def condition_role_chain_count(runs, scenario_ids, params):
    return min(sum(run.role_complete for run in runs), params["count"]), params["count"]


def condition_outcome_min(runs, scenario_ids, params):
    wanted = OUTCOMES.index(params["outcome"])
    done = {run.scenario_id for run in runs if OUTCOMES.index(run.outcome) >= wanted}
    return len(done & set(scenario_ids)), len(scenario_ids)


# тип условия: функция прогресса (сделано, всего), обязательные параметры, нужен ли список сценариев
CONDITIONS = {
    "no_incident_all": (condition_no_incident_all, {}, True),
    "role_chain_count": (condition_role_chain_count, {"count": int}, False),
    "outcome_min": (condition_outcome_min, {"outcome": str}, True),
}


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def check_challenges(content) -> list[str]:
    """Сообщения о неполных записях challenges.yaml; пустой список означает, что справочник цел."""
    items = content.challenges
    if not isinstance(items, list):
        return ["challenges.yaml должен быть списком челленджей"]
    problems = []
    seen = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not all(is_text(item.get(name)) for name in TEXT_FIELDS):
            problems.append(f"запись {index}: нужны непустые строки {', '.join(TEXT_FIELDS)}")
            continue
        if item["id"] in seen:
            problems.append(f"{item['id']}: id повторяется")
        seen.add(item["id"])
        problems += [f"{item['id']}: {problem}" for problem in check_item(item)]
    return problems


def check_item(item):
    problems = []
    for name in COUNT_FIELDS:
        value = item.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            problems.append(f"{name} должно быть целым числом больше нуля")
    ids = item.get("scenario_ids")
    if not isinstance(ids, list) or not all(is_text(scenario_id) for scenario_id in ids):
        problems.append("scenario_ids должен быть списком id сценариев, пустой список означает любой")
        ids = []
    elif len(ids) != len(set(ids)):
        problems.append("scenario_ids не должен содержать повторы")
    condition = item.get("condition")
    if not isinstance(condition, dict) or condition.get("type") not in CONDITIONS:
        problems.append(f"condition.type должен быть одним из {', '.join(CONDITIONS)}")
        return problems
    _, spec, needs_scenarios = CONDITIONS[condition["type"]]
    params = condition.get("params") if isinstance(condition.get("params"), dict) else {}
    problems += [f"в condition.params нет {name}" for name in spec if name not in params]
    for name, value in params.items():
        kind = spec.get(name)
        if kind is None:
            problems.append(f"в condition.params лишний ключ {name}")
        elif isinstance(value, bool) or not isinstance(value, kind) or (kind is int and value <= 0):
            expected = "строкой" if kind is str else "целым числом больше нуля"
            problems.append(f"параметр {name} должен быть {expected}")
    if params.get("outcome") is not None and params["outcome"] not in OUTCOMES:
        problems.append(f"исход должен быть одним из {', '.join(OUTCOMES)}")
    if needs_scenarios and not ids:
        problems.append(f"условию {condition['type']} нужен непустой scenario_ids")
    return problems


def activate(db, content, now):
    """Создаёт окно каждому челленджу из YAML, которого ещё нет в таблице, и уведомляет всех
    сотрудников; возвращает id новых. Вызывающий фиксирует транзакцию."""
    # При первом запуске у ContentStore ещё нет прежней проверенной версии справочников.
    if check_challenges(content):
        return []
    existing = set(db.scalars(select(Challenge.id)))
    employee_ids = None
    activated = []
    for item in content.challenges:
        if item["id"] in existing:
            continue
        params = item["condition"].get("params") or {}
        challenge = Challenge(
            id=item["id"],
            title=item["title"],
            description=item["description"],
            scenario_ids_json=list(item["scenario_ids"]),
            condition_json={"type": item["condition"]["type"], "params": dict(params)},
            bonus_points=item["bonus_points"],
            starts_at=now,
            ends_at=now + timedelta(days=item["duration_days"]),
            created_at=now,
        )
        db.add(challenge)
        db.flush()
        if employee_ids is None:
            employee_ids = db.scalars(select(Employee.id).order_by(Employee.id)).all()
        for employee_id in employee_ids:
            notify_new(db, employee_id, challenge, content.rules, now)
        activated.append(item["id"])
    return activated


def notify_new(db, employee_id, challenge, rules, now):
    bonus = plural(challenge.bonus_points, "балл", "балла", "баллов")
    ttl_days = rules["bonus"]["challenge_bonus_ttl_hours"] // 24
    lasts = plural(ttl_days, "день", "дня", "дней")
    payload = {
        "challenge_id": challenge.id,
        "bonus_points": challenge.bonus_points,
        "ends_at": clock.iso(challenge.ends_at),
    }
    notifications.create(
        db,
        employee_id,
        "challenge",
        f"Челлендж «{challenge.title}» до {date_words(challenge.ends_at)}",
        f"{challenge.description} Бонус {bonus}, действует {lasts} после выполнения.",
        payload,
        f"challenge_new:{challenge.id}:{employee_id}",
        now,
    )


def announce_active(db, employee_id, rules, now):
    """Сотрудник, появившийся после активации (например, из HR-системы), получает анонсы
    идущих челленджей: условия для него те же, бонусы начисляются."""
    active = select(Challenge).where(Challenge.starts_at <= now, Challenge.ends_at > now)
    for challenge in db.scalars(active.order_by(Challenge.id)):
        notify_new(db, employee_id, challenge, rules, now)


def runs_in_window(db, employee_id, challenge):
    # столбцы, а не объекты: итог текущего прохождения записан условным UPDATE, объект в сессии его не видит
    columns = (ScenarioRun.scenario_id, ScenarioRun.outcome, ScenarioRun.role_complete)
    query = select(*columns).where(
        ScenarioRun.employee_id == employee_id,
        ScenarioRun.status == "finished",
        ScenarioRun.finished_at >= challenge.starts_at,
        ScenarioRun.finished_at < challenge.ends_at,
    )
    if challenge.scenario_ids_json:
        query = query.where(ScenarioRun.scenario_id.in_(challenge.scenario_ids_json))
    return db.execute(query).all()


def progress(db, employee_id, challenge):
    check, _, _ = CONDITIONS[challenge.condition_json["type"]]
    params = challenge.condition_json.get("params") or {}
    done, total = check(runs_in_window(db, employee_id, challenge), challenge.scenario_ids_json, params)
    return {"done": done, "total": total, "completed": total > 0 and done >= total}


def evaluate(db, content, employee, run_id, now) -> list[dict]:
    """После завершения прохождения проверяет активные челленджи и начисляет бонус за каждый
    выполненный впервые; возвращает выполненные для разбора."""
    active = select(Challenge).where(Challenge.starts_at <= now, Challenge.ends_at > now)
    rows = db.scalars(active.order_by(Challenge.id)).all()
    if not rows:
        return []
    earned_query = select(BonusPoint.challenge_id).where(
        BonusPoint.employee_id == employee.id, BonusPoint.challenge_id.is_not(None)
    )
    earned = set(db.scalars(earned_query))
    ttl = timedelta(hours=content.rules["bonus"]["challenge_bonus_ttl_hours"])
    completed = []
    for challenge in rows:
        if challenge.id in earned or not progress(db, employee.id, challenge)["completed"]:
            continue
        completed.append(award(db, employee, challenge, run_id, now + ttl, now))
    return completed


def award(db, employee, challenge, run_id, expires_at, now):
    points = plural(challenge.bonus_points, "балл", "балла", "баллов")
    db.add(
        BonusPoint(
            employee_id=employee.id,
            points=challenge.bonus_points,
            reason=f"Челлендж «{challenge.title}»",
            challenge_id=challenge.id,
            run_id=run_id,
            earned_at=now,
            expires_at=expires_at,
        )
    )
    payload = {
        "challenge_id": challenge.id,
        "bonus_points": challenge.bonus_points,
        "expires_at": clock.iso(expires_at),
    }
    notifications.create(
        db,
        employee.id,
        "challenge",
        f"Челлендж выполнен: {challenge.title}",
        f"Начислено {points} к рейтингу, они сгорают {date_words(expires_at)}.",
        payload,
        f"challenge_done:{challenge.id}:{employee.id}",
        now,
    )
    outbox.emit(
        db,
        "challenge_completed",
        payload | {"employee_code": employee.code, "title": challenge.title, "run_id": run_id},
        now,
    )
    return {
        "id": challenge.id,
        "title": challenge.title,
        "bonus_points": challenge.bonus_points,
        "bonus_expires_at": clock.iso(expires_at),
    }


def list_for(db, content, employee, now):
    """Челленджи для сотрудника с прогрессом и статусом; тексты берутся из текущего YAML, а
    условия и окно из таблицы, как их объявили при активации."""
    texts = {item["id"]: item for item in content.challenges}
    order = {item["id"]: index for index, item in enumerate(content.challenges)}
    rows = db.scalars(select(Challenge)).all()
    # порядок как в YAML, убранные из файла челленджи в конце
    rows.sort(key=lambda row: (order.get(row.id, len(order)), row.starts_at, row.id))
    bonus_query = select(BonusPoint).where(
        BonusPoint.employee_id == employee.id, BonusPoint.challenge_id.is_not(None)
    )
    bonuses = {row.challenge_id: row for row in db.scalars(bonus_query)}
    return [
        view(row, texts.get(row.id), bonuses.get(row.id), progress(db, employee.id, row), now) for row in rows
    ]


def view(row, text, bonus, progress_view, now):
    if bonus is not None:
        status = "completed"
    elif now < row.ends_at:
        status = "active"
    else:
        status = "expired"
    return {
        "id": row.id,
        "title": text["title"] if text else row.title,
        "description": text["description"] if text else row.description,
        "scenario_ids": list(row.scenario_ids_json),
        "bonus_points": row.bonus_points,
        "starts_at": clock.iso(row.starts_at),
        "ends_at": clock.iso(row.ends_at),
        "progress": progress_view,
        "bonus_expires_at": clock.iso(bonus.expires_at) if bonus else None,
        "status": status,
    }
