"""Достижения по декларативным правилам из content/achievements.yaml. Здесь реестр типов правил
(функция проверки и обязательные параметры), проверка формы справочника для загрузчика и выдача
по событию завершения прохождения: правила проверяются только для ещё не полученных
достижений, запись защищена уникальностью (employee_id, achievement_id), вместе с ней создаются
уведомление и событие outbox. Самих условий в коде нет: числа и коды приходят из YAML."""

from sqlalchemy import select

from app import clock
from app.models import AchievementEarned, RunStep, ScenarioRun
from app.scenarios.engine import OUTCOMES
from app.scenarios.schema import VERDICTS
from app.services import notifications, outbox

TEXT_FIELDS = ("id", "title", "description", "rule_text")
SCALES = ("loyalty", "safety")


def rule_first_run(facts, params):
    return len(facts["history"]) == 1


def rule_role_chain(facts, params):
    return sum(item["role_complete"] for item in facts["history"]) >= params["times"]


def rule_timers_on_time(facts, params):
    answered = sum(item["timers_answered"] for item in facts["history"])
    if facts["run"]["expired_timers"] > params["run_expired"]:
        return False
    return answered >= params["total_answered_min"]


def rule_streak_no_incident(facts, params):
    recent = facts["history"][: params["runs"]]
    return len(recent) == params["runs"] and all(item["outcome"] != "incident" for item in recent)


def rule_outcome_in_class(facts, params):
    run = facts["run"]
    if params.get("native_class") and not run["native_class"]:
        return False
    if run["service_class"] != params["service_class"]:
        return False
    return OUTCOMES.index(run["outcome"]) >= OUTCOMES.index(params["outcome"])


def rule_all_critical_exemplary(facts, params):
    critical = facts["critical_scenarios"]
    if len(critical) < params["min_scenarios"]:
        return False
    return all(facts["best_outcomes"].get(scenario_id) == "exemplary" for scenario_id in critical)


def rule_competency_mastery(facts, params):
    item = facts["mastery"].get(params["competency"])
    if item is None or item["mastery"] is None:
        return False
    return item["runs_assessed"] >= params["runs_min"] and item["mastery"] >= params["mastery_min"]


def rule_escalation_channel(facts, params):
    return len(facts["channels"].get(params["verdict"], ())) >= params["distinct_targets"]


def rule_scale_min(facts, params):
    run = facts["run"]
    if params.get("critical") and not run["critical"]:
        return False
    return run[params["scale"]] >= params["min"]


NUMBER = (int, float)
# тип правила: функция проверки и обязательные параметры с типами; значения читаются из YAML как есть,
# поэтому строка вместо числа ловится здесь, а не TypeError при завершении прохождения
RULES = {
    "first_run": (rule_first_run, {}),
    "role_chain": (rule_role_chain, {"times": int}),
    "timers_on_time": (rule_timers_on_time, {"run_expired": int, "total_answered_min": int}),
    "streak_no_incident": (rule_streak_no_incident, {"runs": int}),
    "outcome_in_class": (rule_outcome_in_class, {"service_class": str, "outcome": str}),
    "all_critical_exemplary": (rule_all_critical_exemplary, {"min_scenarios": int}),
    "competency_mastery": (
        rule_competency_mastery,
        {"competency": str, "mastery_min": NUMBER, "runs_min": int},
    ),
    "escalation_channel": (rule_escalation_channel, {"distinct_targets": int, "verdict": str}),
    "scale_min": (rule_scale_min, {"scale": str, "min": int}),
}
OPTIONAL_PARAMS = {"native_class": bool, "critical": bool}


def check_achievements(content) -> list[str]:
    """Сообщения о неполных записях achievements.yaml; пустой список означает, что справочник цел."""
    items = content.achievements
    if not isinstance(items, list):
        return ["achievements.yaml должен быть списком достижений"]
    problems = []
    seen = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not all(is_text(item.get(name)) for name in TEXT_FIELDS):
            problems.append(f"запись {index}: нужны непустые строки {', '.join(TEXT_FIELDS)} и словарь rule")
            continue
        if item["id"] in seen:
            problems.append(f"{item['id']}: id повторяется")
        seen.add(item["id"])
        rule = item.get("rule")
        if not isinstance(rule, dict) or rule.get("type") not in RULES:
            problems.append(f"{item['id']}: rule.type должен быть одним из {', '.join(RULES)}")
            continue
        params = rule.get("params") if isinstance(rule.get("params"), dict) else {}
        found = check_params(params, RULES[rule["type"]][1])
        if not found:
            found = check_codes(content, params)
        problems += [f"{item['id']}: {problem}" for problem in found]
    return problems


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def check_params(params, spec):
    """Обязательные параметры на месте и нужного типа, необязательные булевы, лишних нет."""
    problems = [f"в params нет {name}" for name in spec if name not in params]
    for name, value in params.items():
        kind = spec.get(name) or OPTIONAL_PARAMS.get(name)
        if kind is None:
            problems.append(f"в params лишний ключ {name}")
        elif kind is bool and not isinstance(value, bool):
            problems.append(f"параметр {name} должен быть true или false")
        elif kind is not bool and (isinstance(value, bool) or not isinstance(value, kind)):
            expected = "строкой" if kind is str else "числом"
            problems.append(f"параметр {name} должен быть {expected}")
        elif kind is not str and kind is not bool and value < 0:
            problems.append(f"параметр {name} не может быть отрицательным")
    return problems


def check_codes(content, params):
    """Коды в параметрах правила должны существовать в справочниках, иначе правило никогда не сработает."""
    problems = []
    codes = {item.get("code") for item in content.competencies if isinstance(item, dict)}
    if "competency" in params and params["competency"] not in codes:
        problems.append(f"компетенции «{params['competency']}» нет в competencies.yaml")
    if "service_class" in params and params["service_class"] not in content.classes:
        problems.append(f"класса «{params['service_class']}» нет в classes.yaml")
    if "outcome" in params and params["outcome"] not in OUTCOMES:
        problems.append(f"исход должен быть одним из {', '.join(OUTCOMES)}")
    if "verdict" in params and params["verdict"] not in VERDICTS:
        problems.append(f"вердикт должен быть одним из {', '.join(VERDICTS)}")
    if "scale" in params and params["scale"] not in SCALES:
        problems.append(f"шкала должна быть одной из {', '.join(SCALES)}")
    return problems


def gather_facts(db, content, employee_id, run, mastery):
    """Всё, что читают правила: это прохождение, история завершённых прохождений от нового к
    старому, лучший исход по сценариям, критические сценарии, владение и каналы эскалации."""
    columns = (
        ScenarioRun.scenario_id,
        ScenarioRun.outcome,
        ScenarioRun.role_complete,
        ScenarioRun.timers_answered,
        ScenarioRun.expired_timers,
    )
    rows = db.execute(
        select(*columns)
        .where(ScenarioRun.employee_id == employee_id, ScenarioRun.status == "finished")
        .order_by(ScenarioRun.id.desc())
    ).all()
    history = [row._asdict() for row in rows]
    best = {}
    for item in history:
        current = best.get(item["scenario_id"])
        if current is None or OUTCOMES.index(item["outcome"]) > OUTCOMES.index(current):
            best[item["scenario_id"]] = item["outcome"]
    channel_rows = db.execute(
        select(RunStep.verdict, RunStep.escalation_target)
        .join(ScenarioRun, ScenarioRun.id == RunStep.run_id)
        .where(ScenarioRun.employee_id == employee_id, RunStep.escalation_target.is_not(None))
        .distinct()
    ).all()
    channels = {}
    for verdict, target in channel_rows:
        channels.setdefault(verdict, set()).add(target)
    return {
        "run": run,
        "history": history,
        "best_outcomes": best,
        "critical_scenarios": [key for key, item in content.scenarios.items() if item.get("critical")],
        "mastery": {item["code"]: item for item in mastery},
        "channels": channels,
    }


def evaluate(db, content, employee, run, mastery, now) -> list[dict]:
    """Проверяет правила ещё не полученных достижений по завершённому прохождению run (словарь
    с run_id, исходом, классом, шкалами и счётчиками) и возвращает выданные записи справочника."""
    query = select(AchievementEarned.achievement_id).where(AchievementEarned.employee_id == employee.id)
    earned = set(db.scalars(query))
    pending = [item for item in content.achievements if item["id"] not in earned]
    if not pending:
        return []
    facts = gather_facts(db, content, employee.id, run, mastery)
    awarded = []
    for item in pending:
        check, _ = RULES[item["rule"]["type"]]
        if not check(facts, item["rule"].get("params") or {}):
            continue
        db.add(
            AchievementEarned(
                employee_id=employee.id, achievement_id=item["id"], run_id=run["run_id"], earned_at=now
            )
        )
        payload = {"achievement_id": item["id"], "run_id": run["run_id"]}
        notifications.create(
            db,
            employee.id,
            "achievement",
            f"Достижение: {item['title']}",
            item["description"],
            payload,
            f"achievement:{item['id']}:{employee.id}",
            now,
        )
        outbox.emit(
            db,
            "achievement_earned",
            {
                "employee_code": employee.code,
                "achievement_id": item["id"],
                "title": item["title"],
                "run_id": run["run_id"],
                "earned_at": clock.iso(now),
            },
            now,
        )
        awarded.append(item)
    return awarded
