"""Форма DSL сценария: допустимые ключи, типы, диапазоны из rules.yaml, ссылки на справочники.
Каждое отклонение это Finding с кодом; строка берётся из LineDict загрузчика. Проверки графа,
путей и шкал живут в validator.py, здесь только то, что видно по одному узлу или варианту."""

import re

from app.scenarios.engine import ROLE_CHAIN
from app.scenarios.findings import is_int, is_text

ESCALATION_TARGETS = "chief ptb engineer police medics_station pa_announcement driver station".split()
NODE_TYPES = ("dialog", "event", "ending")
VERDICTS = ("best", "ok", "bad")
FORCED_OUTCOMES = ("incident", "acceptable")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# допустимые поля каждого блока DSL; всё, чего нет в списке, это ошибка schema (ловит опечатки)
KEYS = {
    "scenario": "id version title summary source_situations difficulty critical tags competencies role_model "
    "estimated_minutes context start outcome_rules nodes",
    "context": "service_class segment next_station_minutes time_of_day passenger crew_available "
    "escalation_expected_by_step loyalty_of",
    "passenger": "label state",
    "start": "node loyalty safety flags",
    "outcome_rules": "incident_if_safety_below exemplary_if",
    "exemplary_if": "safety_min loyalty_min no_expired_timers",
    "dialog": "type text passenger_says timer options",
    "event": "type text passenger_says effects set_flags next",
    "ending": "type title text forced_outcome debrief",
    "timer": "seconds seconds_by_class on_expire",
    "on_expire": "next effects competencies set_flags debrief",
    "option": "id text next effects competencies set_flags role_step escalation_target delayed when debrief",
    "delayed": "steps effects text unless_flags",
    "when": "flags_all flags_none loyalty_min loyalty_max safety_min safety_max chosen_any not_chosen "
    "service_class",
    "debrief": "verdict why better refs",
    "ending_debrief": "summary refs",
    "effects": "loyalty safety",
}
KEYS = {kind: set(names.split()) for kind, names in KEYS.items()}
REQUIRED = {
    "scenario": "id version title summary source_situations difficulty critical tags competencies role_model "
    "estimated_minutes context start nodes",
    "context": "service_class segment next_station_minutes time_of_day passenger crew_available",
    "passenger": "label state",
    "start": "node loyalty safety",
}
REQUIRED = {kind: names.split() for kind, names in REQUIRED.items()}


def keys(checker, obj, kind, label, ignore=()):
    checker.keys(obj, KEYS[kind], REQUIRED.get(kind, ()), label, ignore)


def check_scenario_fields(scenario, checker, file_stem):
    keys(checker, scenario, "scenario", "сценарий")
    scenario_id = scenario.get("id")
    if not isinstance(scenario_id, str) or not ID_PATTERN.match(scenario_id):
        checker.error("schema", "id должен быть латиницей в snake_case", scenario)
    elif file_stem and scenario_id != file_stem:
        checker.error("schema", f"id «{scenario_id}» не совпадает с именем файла «{file_stem}»", scenario)
    checker.integer(scenario.get("version"), "version", scenario, 1)
    checker.text(scenario.get("title"), "title", scenario)
    checker.text(scenario.get("summary"), "summary", scenario)
    sources = scenario.get("source_situations")
    if not isinstance(sources, list) or not sources or any(not is_int(item) for item in sources):
        checker.error("schema", "source_situations должно быть списком номеров карточек", scenario)
    difficulty = checker.limits["difficulty"]
    checker.integer(scenario.get("difficulty"), "difficulty", scenario, difficulty["min"], difficulty["max"])
    checker.boolean(scenario.get("critical"), "critical", scenario)
    checker.boolean(scenario.get("role_model"), "role_model", scenario)
    checker.string_list(scenario.get("tags"), "tags", scenario)
    checker.string_list(scenario.get("competencies"), "competencies", scenario)
    checker.integer(scenario.get("estimated_minutes"), "estimated_minutes", scenario, 1)
    check_context(scenario, checker)
    check_start(scenario, checker)
    check_outcome_rules(scenario.get("outcome_rules"), checker)


def check_context(scenario, checker):
    context = scenario.get("context")
    if not isinstance(context, dict):
        checker.error("schema", "context должен быть словарём", scenario)
        return
    keys(checker, context, "context", "context")
    checker.service_class(context.get("service_class"), context)
    checker.text(context.get("segment"), "context.segment", context)
    checker.integer(context.get("next_station_minutes"), "context.next_station_minutes", context, 0)
    checker.text(context.get("time_of_day"), "context.time_of_day", context)
    passenger = context.get("passenger")
    if not isinstance(passenger, dict):
        checker.error("schema", "context.passenger должен быть словарём с label и state", context)
    else:
        keys(checker, passenger, "passenger", "context.passenger")
        checker.text(passenger.get("label"), "context.passenger.label", passenger)
        checker.text(passenger.get("state"), "context.passenger.state", passenger)
    crew = context.get("crew_available")
    if checker.string_list(crew, "context.crew_available", context, allow_empty=True):
        for code in crew:
            if code not in ESCALATION_TARGETS:
                checker.error(
                    "unknown_escalation_target", f"в crew_available неизвестный канал «{code}»", context
                )
    if "escalation_expected_by_step" in context:
        checker.integer(
            context["escalation_expected_by_step"], "context.escalation_expected_by_step", context, 1
        )
    elif scenario.get("critical") is True:
        checker.warning(
            "escalation_expected_missing", "критический сценарий без escalation_expected_by_step", context
        )
    if "loyalty_of" in context:
        checker.text(context["loyalty_of"], "context.loyalty_of", context)


def check_start(scenario, checker):
    start = scenario.get("start")
    if not isinstance(start, dict):
        checker.error("schema", "start должен быть словарём с node, loyalty, safety", scenario)
        return
    keys(checker, start, "start", "start")
    checker.text(start.get("node"), "start.node", start)
    bounds = checker.content.rules["scales"]
    checker.integer(start.get("loyalty"), "start.loyalty", start, bounds["min"], bounds["max"])
    checker.integer(start.get("safety"), "start.safety", start, bounds["min"], bounds["max"])
    checker.flags(start.get("flags"), "start.flags", start)


def check_outcome_rules(rules, checker):
    if rules is None:
        return
    if not isinstance(rules, dict):
        checker.error("schema", "outcome_rules должен быть словарём", rules)
        return
    keys(checker, rules, "outcome_rules", "outcome_rules")
    bounds = checker.content.rules["scales"]
    if "incident_if_safety_below" in rules:
        checker.integer(
            rules["incident_if_safety_below"], "incident_if_safety_below", rules, bounds["min"], bounds["max"]
        )
    exemplary = rules.get("exemplary_if")
    if exemplary is not None:
        if not isinstance(exemplary, dict):
            checker.error("schema", "exemplary_if должен быть словарём", rules)
            return
        keys(checker, exemplary, "exemplary_if", "exemplary_if")
        for key in ("safety_min", "loyalty_min"):
            if key in exemplary:
                checker.integer(
                    exemplary[key], f"exemplary_if.{key}", exemplary, bounds["min"], bounds["max"]
                )
        if "no_expired_timers" in exemplary:
            checker.boolean(exemplary["no_expired_timers"], "exemplary_if.no_expired_timers", exemplary)


def check_node(node_id, node, scenario, checker):
    checker.node = node_id
    checker.option = None
    if not ID_PATTERN.match(str(node_id)):
        checker.error("schema", "id узла должен быть латиницей в snake_case", node)
    if not isinstance(node, dict):
        checker.error("schema", "узел должен быть словарём", scenario["nodes"])
        return
    node_type = node.get("type")
    if node_type not in NODE_TYPES:
        checker.error("schema", "type узла должен быть dialog, event или ending", node)
        return
    if node_type != "dialog" and "timer" in node:
        checker.error("timer_on_non_dialog", "таймер допустим только у узла dialog", node)
    keys(checker, node, node_type, f"узел {node_type}", ignore=("timer",))
    checker.text(node.get("text"), "text", node, checker.limits["node_text_max"])
    if "passenger_says" in node:
        checker.text(node["passenger_says"], "passenger_says", node)
    if node_type == "dialog":
        check_dialog(node, scenario, checker)
    elif node_type == "event":
        checker.effects(node.get("effects"), node)
        checker.flags(node.get("set_flags"), "set_flags", node)
        if not is_text(node.get("next")):
            checker.error("dead_end", "у события нет перехода next", node)
    else:
        check_ending(node, checker)


def check_dialog(node, scenario, checker):
    options = node.get("options")
    if not isinstance(options, list) or not options:
        checker.error("dead_end", "у диалога нет вариантов", node)
        options = []
    elif len(options) < checker.limits["min_options"]:
        checker.error("schema", f"у диалога не меньше {checker.limits['min_options']} вариантов", node)
    timer = node.get("timer")
    if timer is not None:
        check_timer(timer, checker)
    for option in options:
        check_option(option, scenario, checker, timer is not None)
    checker.option = None
    if timer is not None and is_int(timer.get("seconds")):
        many = len(options) >= checker.limits["short_timer_options"]
        if timer["seconds"] < checker.limits["short_timer_seconds"] and many:
            checker.warning("short_timer_many_options", "короткий таймер и четыре и больше вариантов", node)


def check_timer(timer, checker):
    if not isinstance(timer, dict):
        checker.error("schema", "timer должен быть словарём", timer)
        return
    keys(checker, timer, "timer", "timer")
    bounds = checker.limits["timer_seconds"]
    seconds = timer.get("seconds")
    by_class = timer.get("seconds_by_class")
    if seconds is None and by_class is None:
        checker.error("schema", "у таймера нужны seconds или seconds_by_class", timer)
    if seconds is not None:
        checker.integer(seconds, "timer.seconds", timer, bounds["min"], bounds["max"])
    if by_class is not None:
        check_seconds_by_class(by_class, seconds, timer, checker)
    on_expire = timer.get("on_expire")
    if not isinstance(on_expire, dict) or not is_text(on_expire.get("next")):
        checker.error("timer_without_expire", "у таймера нет ветки on_expire с переходом next", timer)
        return
    keys(checker, on_expire, "on_expire", "on_expire")
    checker.effects(on_expire.get("effects"), on_expire)
    checker.competency_points(on_expire.get("competencies"), on_expire)
    checker.flags(on_expire.get("set_flags"), "set_flags", on_expire)
    check_debrief(on_expire.get("debrief"), on_expire, checker, verdict="bad")


def check_seconds_by_class(by_class, seconds, timer, checker):
    if not isinstance(by_class, dict):
        checker.error("schema", "seconds_by_class должно быть словарём класс: секунды", timer)
        return
    bounds = checker.limits["timer_seconds"]
    for code, value in by_class.items():
        checker.service_class(code, timer)
        checker.integer(value, f"seconds_by_class.{code}", timer, bounds["min"], bounds["max"])
    missing = [code for code in checker.content.classes if code not in by_class]
    if seconds is None and missing:
        checker.error(
            "seconds_by_class_incomplete",
            f"нет seconds по умолчанию и нет классов {', '.join(missing)}",
            timer,
        )


def check_option(option, scenario, checker, with_timer):
    if not isinstance(option, dict):
        checker.error("schema", "вариант должен быть словарём", option)
        return
    checker.option = option.get("id") if isinstance(option.get("id"), str) else None
    keys(checker, option, "option", "вариант")
    if not isinstance(option.get("id"), str) or not ID_PATTERN.match(option["id"]):
        checker.error("schema", "id варианта должен быть латиницей в snake_case", option)
    if checker.text(option.get("text"), "text", option, checker.limits["option_text_max"]) and with_timer:
        if len(option["text"]) > checker.limits["option_text_max_with_timer"]:
            checker.warning(
                "option_text_long_for_timer", "текст варианта под таймером длиннее 120 знаков", option
            )
    if not is_text(option.get("next")):
        checker.error("schema", "у варианта нет перехода next", option)
    checker.effects(option.get("effects"), option)
    checker.competency_points(option.get("competencies"), option)
    checker.flags(option.get("set_flags"), "set_flags", option)
    if "role_step" in option and option["role_step"] not in ROLE_CHAIN:
        checker.error(
            "unknown_role_step", f"role_step «{option['role_step']}» не из {', '.join(ROLE_CHAIN)}", option
        )
    check_escalation(option, scenario, checker)
    for item in option.get("delayed") or []:
        check_delayed(item, checker)
    if "when" in option:
        check_when(option["when"], scenario, checker)
    check_debrief(option.get("debrief"), option, checker)


def check_escalation(option, scenario, checker):
    target = option.get("escalation_target")
    if target is None:
        return
    if target not in ESCALATION_TARGETS:
        checker.error(
            "unknown_escalation_target", f"канал «{target}» не из {', '.join(ESCALATION_TARGETS)}", option
        )
        return
    crew = (scenario.get("context") or {}).get("crew_available")
    if isinstance(crew, list) and target not in crew:
        checker.error(
            "escalation_target_unavailable", f"канала «{target}» нет в context.crew_available", option
        )


def check_delayed(item, checker):
    if not isinstance(item, dict):
        checker.error("schema", "элемент delayed должен быть словарём", item)
        return
    keys(checker, item, "delayed", "delayed")
    bounds = checker.limits["delayed_steps"]
    if not is_int(item.get("steps")) or not bounds["min"] <= item["steps"] <= bounds["max"]:
        checker.error(
            "delayed_steps_out_of_range",
            f"delayed.steps должно быть от {bounds['min']} до {bounds['max']}",
            item,
        )
    checker.effects(item.get("effects"), item)
    checker.text(item.get("text"), "delayed.text", item)
    checker.flags(item.get("unless_flags"), "unless_flags", item)


def check_when(when, scenario, checker):
    if not isinstance(when, dict) or not when:
        checker.error("schema", "when должно быть непустым словарём условий", when)
        return
    keys(checker, when, "when", "when")
    checker.flags(when.get("flags_all"), "when.flags_all", when)
    if "flags_none" in when:
        checker.string_list(when["flags_none"], "when.flags_none", when)
    bounds = checker.content.rules["scales"]
    for key in ("loyalty_min", "loyalty_max", "safety_min", "safety_max"):
        if key in when:
            checker.integer(when[key], f"when.{key}", when, bounds["min"], bounds["max"])
    known = all_option_ids(scenario)
    for key in ("chosen_any", "not_chosen"):
        if key in when and checker.string_list(when[key], f"when.{key}", when):
            for option_id in when[key]:
                if option_id not in known:
                    checker.error("unknown_option_in_condition", f"в {key} нет варианта «{option_id}»", when)
    if "service_class" in when and checker.string_list(when["service_class"], "when.service_class", when):
        for code in when["service_class"]:
            checker.service_class(code, when)


def check_debrief(debrief, where, checker, verdict=None):
    if not isinstance(debrief, dict):
        checker.error("missing_why", "нет разбора debrief с why и refs", where)
        return
    keys(checker, debrief, "debrief", "debrief")
    if verdict is None:
        verdict = debrief.get("verdict")
        if verdict not in VERDICTS:
            checker.error("schema", "verdict должен быть best, ok или bad", debrief)
    if not is_text(debrief.get("why")):
        checker.error("missing_why", "в разборе нет why", debrief)
    if verdict != "best" and not is_text(debrief.get("better")):
        checker.error("missing_better", "при verdict не best нужен better: как поступить лучше", debrief)
    checker.refs(debrief.get("refs"), debrief)


def check_ending(node, checker):
    checker.text(node.get("title"), "title", node)
    if "forced_outcome" in node and node["forced_outcome"] not in FORCED_OUTCOMES:
        checker.error("schema", "forced_outcome должен быть incident или acceptable", node)
    debrief = node.get("debrief")
    if not isinstance(debrief, dict):
        checker.error("missing_summary", "у концовки нет debrief с summary и refs", node)
        return
    keys(checker, debrief, "ending_debrief", "debrief концовки")
    if not is_text(debrief.get("summary")):
        checker.error("missing_summary", "в разборе концовки нет summary", debrief)
    checker.refs(debrief.get("refs"), debrief)


def all_option_ids(scenario):
    ids = []
    for node in scenario["nodes"].values():
        if isinstance(node, dict):
            for option in node.get("options") or []:
                if isinstance(option, dict) and isinstance(option.get("id"), str):
                    ids.append(option["id"])
    return ids
