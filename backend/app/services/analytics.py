"""Аналитика по данным прохождений. Владение компетенциями считается по окну последних
завершённых прохождений сотрудника (формулы в scoring.py, числа в rules.yaml) и пересчитывается
в employee_competencies при завершении прохождения. Личный отчёт: проседающие и пробелы,
типичные ошибки, рекомендации сценариев с причиной, темп решений под таймером, своевременность
эскалации в критических сценариях, динамика по неделям и вывод фразой. Отчёт по бригаде в
team_analytics.py собирается из этих же функций. Кроме таблицы владения ничего заранее не хранится."""

from datetime import timedelta

from sqlalchemy import select

from app import clock
from app.models import EmployeeCompetency, RunStep, ScenarioRun
from app.scenarios.engine import OUTCOMES
from app.services import scoring
from app.services.texts import join_titles, plural

# порядок статусов для рекомендаций: сначала проседающие, потом с малым числом оценок, потом пробелы
NEEDS_WORK = {"weak": 0, "few_data": 1, "gap": 2}


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


def finished_runs(db, employee_id):
    """Завершённые прохождения сотрудника от нового к старому."""
    query = select(ScenarioRun).where(
        ScenarioRun.employee_id == employee_id, ScenarioRun.status == "finished"
    )
    return db.scalars(query.order_by(ScenarioRun.id.desc())).all()


def steps_by_run(db, run_ids):
    rows = db.scalars(
        select(RunStep).where(RunStep.run_id.in_(list(run_ids))).order_by(RunStep.step_no)
    ).all()
    grouped = {}
    for row in rows:
        grouped.setdefault(row.run_id, []).append(row)
    return grouped


def titles_of(content):
    return {item["code"]: item["title"] for item in content.competencies}


def best_outcomes(runs):
    best = {}
    for run in runs:
        current = best.get(run.scenario_id)
        if current is None or OUTCOMES.index(run.outcome) > OUTCOMES.index(current):
            best[run.scenario_id] = run.outcome
    return best


def potential(store, scenario_id, code):
    """Максимум очков по компетенции, который сценарий даёт на лучшем пути (считает перебор путей)."""
    analysis = store.analysis(scenario_id)
    return analysis["own"]["potential"].get(code, 0) if analysis else 0


def runs_word(count):
    return plural(count, "прохождению", "прохождениям", "прохождениям")


def points_word(count):
    return plural(count, "очка", "очков", "очков")


def reason_text(item, title, points, rules):
    settings = rules["mastery"]
    gives = f"на лучшем пути сценарий даёт до {points_word(points)} по этой компетенции"
    if item["status"] == "gap":
        return f"{title}: компетенция ещё не оценивалась; {gives}"
    value = f"владение {item['mastery']:.2f} по {runs_word(item['runs_assessed'])}"
    if item["status"] == "few_data":
        need = plural(
            settings["min_runs_assessed"], "разного сценария", "разных сценариев", "разных сценариев"
        )
        return f"{title}: {value}, для вывода нужно не меньше {need}; {gives}"
    return f"{title}: {value}, ниже порога {settings['weak_below']:.2f}; {gives}"


def recommend(store, content, runs, mastery, mistakes, limit):
    """Сценарии для компетенций, которым нужна работа: по каждой берётся сценарий с наибольшим
    потенциалом по ней среди ещё не пройденных образцово; без прохождений это стартовый набор."""
    best = best_outcomes(runs)
    candidates = [key for key in sorted(content.scenarios) if best.get(key) != "exemplary"]
    if not runs:
        return starter_recommendations(content, candidates, limit)
    titles = titles_of(content)
    errors = {item["competency"]: item["count"] for item in mistakes}
    needing = [item for item in mastery if item["status"] in NEEDS_WORK]
    # при равном владении вперёд идёт компетенция, где сотрудник чаще ошибался: там ошибки видны в ходах
    needing.sort(
        key=lambda item: (
            NEEDS_WORK[item["status"]],
            item["mastery"] or 0.0,
            -errors.get(item["code"], 0),
            item["code"],
        )
    )
    result = []
    used = set()
    for item in needing:
        scored = [(potential(store, key, item["code"]), key) for key in candidates if key not in used]
        scored = sorted(
            ((points, key) for points, key in scored if points > 0), key=lambda pair: (-pair[0], pair[1])
        )
        if not scored:
            continue
        points, key = scored[0]
        used.add(key)
        result.append(
            {
                "scenario_id": key,
                "title": content.scenarios[key]["title"],
                "competency": item["code"],
                "reason": reason_text(item, titles[item["code"]], points, content.rules),
            }
        )
        if len(result) == limit:
            break
    return result


def starter_recommendations(content, candidates, limit):
    titles = titles_of(content)
    ordered = sorted(candidates, key=lambda key: (content.scenarios[key]["difficulty"], key))
    result = []
    for key in ordered[:limit]:
        scenario = content.scenarios[key]
        assessed = join_titles(titles.get(code, code) for code in scenario["competencies"])
        result.append(
            {
                "scenario_id": key,
                "title": scenario["title"],
                "competency": None,
                "reason": f"Прохождений пока нет: сложность {scenario['difficulty']}, оцениваются {assessed}",
            }
        )
    return result


def tempo_of(runs):
    """Темп решений под таймером по окну прохождений: среднее время ответа считается только по
    отвеченным таймерам, иначе одна забытая вкладка испортила бы среднее."""
    answered = expired = 0
    seconds = []
    for run in runs:
        for step in run.state_json["steps"]:
            if not step.get("timer_seconds"):
                continue
            if step["expired"]:
                expired += 1
            else:
                answered += 1
                seconds.append(step["answered_in_seconds"])
    total = answered + expired
    return {
        "answered_avg_seconds": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "timers_answered": answered,
        "timers_expired": expired,
        "on_time_share": round(answered / total, 2) if total else None,
    }


def escalation_of(content, runs, steps, window_ids):
    """Своевременность эскалации в критических сценариях: бригада вызвана не позже шага
    escalation_expected_by_step хорошим или лучшим вариантом; needless это вызовы с вердиктом
    bad в окне прохождений."""
    critical = on_time = 0
    for run in runs:
        scenario = content.scenarios.get(run.scenario_id) or {}
        expected = scenario.get("context", {}).get("escalation_expected_by_step")
        if not scenario.get("critical") or expected is None:
            continue
        critical += 1
        rows = steps.get(run.id, [])
        if any(
            row.step_no <= expected and row.escalation_target and row.verdict in ("best", "ok")
            for row in rows
        ):
            on_time += 1
    needless = sum(
        1
        for run_id in window_ids
        for row in steps.get(run_id, [])
        if row.escalation_target and row.verdict == "bad"
    )
    return {
        "critical_runs": critical,
        "on_time": on_time,
        "share": round(on_time / critical, 2) if critical else None,
        "needless": needless,
    }


def mistakes_of(window, steps, titles):
    """Отрицательные очки по компетенциям в окне прохождений: сколько раз и в каком сценарии
    последний раз; окно идёт от нового к старому, поэтому первый встреченный сценарий и есть последний."""
    counts = {}
    for run in window:
        for row in steps.get(run.id, []):
            for code, points in row.competencies_json.items():
                if points >= 0:
                    continue
                entry = counts.setdefault(
                    code,
                    {
                        "competency": code,
                        "title": titles.get(code, code),
                        "count": 0,
                        "last_scenario_id": run.scenario_id,
                    },
                )
                entry["count"] += 1
    return sorted(counts.values(), key=lambda item: (-item["count"], item["competency"]))


def weekly_of(runs, now, weeks):
    """Динамика по неделям от понедельника: число прохождений, средний счёт, инциденты, XP."""
    current = (now - timedelta(days=now.weekday())).date()
    starts = [current - timedelta(weeks=back) for back in range(weeks - 1, -1, -1)]
    buckets = {start: {"runs": 0, "scores": [], "incidents": 0, "xp": 0} for start in starts}
    for run in runs:
        day = run.finished_at.date()
        bucket = buckets.get(day - timedelta(days=day.weekday()))
        if bucket is None:
            continue
        bucket["runs"] += 1
        bucket["scores"].append(run.score)
        bucket["incidents"] += run.outcome == "incident"
        bucket["xp"] += run.xp_earned
    return [
        {
            "week_start": start.isoformat(),
            "runs": bucket["runs"],
            "avg_score": round(sum(bucket["scores"]) / len(bucket["scores"])) if bucket["scores"] else None,
            "incidents": bucket["incidents"],
            "xp": bucket["xp"],
        }
        for start, bucket in buckets.items()
    ]


def personal_summary(titles, runs, weak, gaps, recommendations, tempo, escalation):
    if not runs:
        return "Прохождений пока нет: начните с рекомендованных сценариев."
    if weak:
        opening = f"Проседают {join_titles(titles[code] for code in weak)}"
    elif gaps:
        opening = f"Ещё не оценивались {join_titles(titles[code] for code in gaps)}"
    else:
        opening = "Все компетенции оценены и держатся выше порога"
    facts = []
    timers = tempo["timers_answered"] + tempo["timers_expired"]
    if timers:
        facts.append(f"таймеры вовремя {tempo['timers_answered']} из {timers}")
    if escalation["critical_runs"]:
        facts.append(
            f"в критических сценариях бригада вызвана вовремя в {escalation['on_time']} из "
            f"{plural(escalation['critical_runs'], 'прохождения', 'прохождений', 'прохождений')}"
        )
    first = f"{opening}; {', '.join(facts)}." if facts else f"{opening}."
    if not recommendations:
        return first
    return f"{first} Начните со сценария «{recommendations[0]['title']}»."


def personal(db, store, employee, now):
    content = store.content()
    rules = content.rules
    titles = titles_of(content)
    runs = finished_runs(db, employee.id)
    window = runs[: rules["mastery"]["window_runs"]]
    steps = steps_by_run(db, [run.id for run in runs]) if runs else {}
    mastery = mastery_for(db, content, employee.id)
    weak = [item["code"] for item in mastery if item["status"] == "weak"]
    gaps = [item["code"] for item in mastery if item["status"] == "gap"]
    mistakes = mistakes_of(window, steps, titles)
    recommendations = recommend(
        store, content, runs, mastery, mistakes, rules["analytics"]["recommendations"]
    )
    tempo = tempo_of(window)
    escalation = escalation_of(content, runs, steps, [run.id for run in window])
    return {
        "competencies": [item | {"title": titles[item["code"]]} for item in mastery],
        "weak": weak,
        "gaps": gaps,
        "mistakes": mistakes,
        "recommendations": recommendations,
        "tempo": tempo,
        "escalation": escalation,
        "weekly": weekly_of(runs, now, rules["analytics"]["weeks"]),
        "summary": personal_summary(titles, runs, weak, gaps, recommendations, tempo, escalation),
        "runs_total": len(runs),
        "last_run_at": clock.iso(runs[0].finished_at) if runs else None,
    }
