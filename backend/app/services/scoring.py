"""Подсчёт результата прохождения и профиля: раскладка XP по формуле из rules.yaml, уровень
по levels.yaml, владение компетенциями по окну прохождений и статус каждой компетенции.
Функции чистые: завершение прохождения и аналитика подают им данные из БД."""

from app.scenarios.engine import round_half_away


def xp_breakdown(outcome, loyalty, safety, timers_answered, role_complete, rules):
    xp = rules["xp"]
    return {
        "base": xp["base"][outcome],
        "scales": round_half_away((loyalty + safety) / xp["scales_divisor"]),
        "tempo": xp["tempo_per_timer"] * timers_answered,
        "role": xp["role_bonus"] if role_complete else 0,
    }


def score_of(breakdown):
    return sum(breakdown.values())


def xp_for(score, is_repeat, rules):
    # повтор сценария даёт долю очков, иначе рейтинг набивался бы одним выученным сценарием
    if not is_repeat:
        return score
    return round_half_away(score * rules["xp"]["repeat_factor"])


def level_for(xp_total, levels):
    current = levels[0]
    following = None
    for index, level in enumerate(levels):
        if xp_total >= level["threshold"]:
            current = level
            following = levels[index + 1] if index + 1 < len(levels) else None
    return {
        "id": current["id"],
        "title": current["title"],
        "threshold": current["threshold"],
        "next_threshold": following["threshold"] if following else None,
        "next_title": following["title"] if following else None,
    }


def mastery(earned, assessed):
    return earned / assessed if assessed else None


def competency_status(value, runs_assessed, rules):
    settings = rules["mastery"]
    if runs_assessed == 0 or value is None:
        return "gap"
    if runs_assessed < settings["min_runs_assessed"]:
        return "few_data"
    if value < settings["weak_below"]:
        return "weak"
    return "ok"


def window_runs(runs, rules):
    """Последнее прохождение каждого сценария среди последних window_runs: повтор одного
    сценария не накручивает владение. runs идут от нового прохождения к старому."""
    seen = set()
    picked = []
    for run in runs[: rules["mastery"]["window_runs"]]:
        if run["scenario_id"] in seen:
            continue
        seen.add(run["scenario_id"])
        picked.append(run)
    return picked


def mastery_by_competency(runs, codes, rules):
    """Владение и статус по каждой компетенции по окну прохождений; runs это словари
    scenario_id, earned, assessed от нового прохождения к старому."""
    window = window_runs(runs, rules)
    result = []
    for code in codes:
        assessed_runs = [run for run in window if (run["assessed"] or {}).get(code, 0) > 0]
        earned = sum((run["earned"] or {}).get(code, 0) for run in assessed_runs)
        assessed = sum(run["assessed"][code] for run in assessed_runs)
        value = mastery(earned, assessed)
        result.append(
            {
                "code": code,
                "earned": earned,
                "assessed": assessed,
                "runs_assessed": len(assessed_runs),
                "mastery": value,
                "status": competency_status(value, len(assessed_runs), rules),
            }
        )
    return result
