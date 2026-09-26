"""Форма content/rules.yaml и пороги исходов. Здесь перечислены ключи, без которых движок,
подсчёт очков и валидатор не могут считать, и объединение умолчаний из rules.yaml с полем
outcome_rules сценария. Самих чисел в коде нет: все они читаются из YAML."""

RULES_KEYS = """
    scales.min scales.max
    outcome.incident_if_safety_below outcome.exemplary_if.safety_min outcome.exemplary_if.loyalty_min
    outcome.exemplary_if.no_expired_timers
    xp.base.exemplary xp.base.acceptable xp.base.incident xp.scales_divisor xp.tempo_per_timer
    xp.role_bonus xp.repeat_factor
    mastery.window_runs mastery.weak_below mastery.min_runs_assessed
    bonus.expiring_notice_hours bonus.challenge_bonus_ttl_hours
    limits.timer_seconds.min limits.timer_seconds.max limits.effects.min limits.effects.max
    limits.competency_points.min limits.competency_points.max limits.delayed_steps.min
    limits.delayed_steps.max limits.difficulty.min limits.difficulty.max limits.node_text_max
    limits.option_text_max limits.option_text_max_with_timer limits.min_options
    limits.short_timer_seconds limits.short_timer_options limits.timer_reading_rate
    limits.diverging_min limits.why_min limits.better_min
    analysis.path_limit analysis.many_paths analysis.min_outcomes analysis.min_scale_spread
    analysis.corridor_share
    analytics.weeks analytics.recommendations
""".split()


def missing_keys(rules):
    """Пути ключей rules.yaml, которых нет; загрузчик печатает их как ошибки справочника."""
    missing = []
    for path in RULES_KEYS:
        value = rules
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            missing.append(path)
    return missing


def outcome_thresholds(scenario, rules):
    """Пороги исхода для сценария: умолчания rules.yaml, поверх них outcome_rules сценария."""
    defaults = rules["outcome"]
    own = scenario.get("outcome_rules") or {}
    exemplary = dict(defaults["exemplary_if"])
    exemplary.update(own.get("exemplary_if") or {})
    incident_below = own.get("incident_if_safety_below", defaults["incident_if_safety_below"])
    return {"incident_if_safety_below": incident_below, "exemplary_if": exemplary}
