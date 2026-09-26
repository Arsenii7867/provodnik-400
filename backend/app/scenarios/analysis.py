"""Перебор путей сценария без часов. Состояние прохождения (шкалы, флаги, выбранные варианты,
очередь отложенных последствий) ведут чистые функции над словарём; по ним валидатор судит о
достижимости исходов, условных вариантах и разбросе шкал, а карта сценария берёт число путей.
Все числа приходят из content: classes.yaml, rules.yaml и outcome_rules сценария."""

import copy
import math

ROLE_CHAIN = ("acknowledge", "rule", "solution", "assure")
CONTINUE = "continue"


def round_half_away(value):
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def start_state(scenario, content, service_class=None):
    start = scenario["start"]
    return {
        "scenario_id": scenario["id"],
        "service_class": service_class or scenario["context"]["service_class"],
        "node": start["node"],
        "step_no": 0,
        "loyalty": start["loyalty"],
        "safety": start["safety"],
        "flags": dict(start.get("flags") or {}),
        "chosen": [],
        "role_chain": [],
        "expired_timers": 0,
        "timers_answered": 0,
        "delayed": [],
        "earned": {},
        "assessed": {},
        "status": "active",
        "outcome": None,
    }


def condition_holds(when, state):
    if not when:
        return True
    flags = state["flags"]
    for name, value in (when.get("flags_all") or {}).items():
        if bool(flags.get(name, False)) != bool(value):
            return False
    if any(flags.get(name, False) for name in when.get("flags_none") or []):
        return False
    if "loyalty_min" in when and state["loyalty"] < when["loyalty_min"]:
        return False
    if "loyalty_max" in when and state["loyalty"] > when["loyalty_max"]:
        return False
    if "safety_min" in when and state["safety"] < when["safety_min"]:
        return False
    if "safety_max" in when and state["safety"] > when["safety_max"]:
        return False
    chosen_any = when.get("chosen_any")
    if chosen_any and not any(option_id in state["chosen"] for option_id in chosen_any):
        return False
    if any(option_id in state["chosen"] for option_id in when.get("not_chosen") or []):
        return False
    classes = when.get("service_class")
    if classes and state["service_class"] not in classes:
        return False
    return True


def available_options(scenario, state):
    node = scenario["nodes"][state["node"]]
    return [option for option in node.get("options") or [] if condition_holds(option.get("when"), state)]


def apply_effects(state, effects, content):
    """Одна функция для варианта, ветки истечения, события и отложенного последствия: лояльность
    масштабируется чувствительностью класса, безопасность нет, обе шкалы держатся в границах."""
    effects = effects or {}
    bounds = content.rules["scales"]
    sensitivity = content.classes[state["service_class"]]["loyalty_sensitivity"]
    loyalty = state["loyalty"] + round_half_away(effects.get("loyalty", 0) * sensitivity)
    safety = state["safety"] + effects.get("safety", 0)
    state["loyalty"] = max(bounds["min"], min(bounds["max"], loyalty))
    state["safety"] = max(bounds["min"], min(bounds["max"], safety))


def tick_delayed(state, content, force=False):
    """Применяет созревшие отложенные последствия (все при force, на входе в концовку);
    последствие отменяется, если к сроку выставлен любой флаг из unless_flags."""
    applied = []
    pending = []
    for item in state["delayed"]:
        if item["due_step"] > state["step_no"] and not force:
            pending.append(item)
            continue
        cancelled = any(
            state["flags"].get(name, False) == value for name, value in item["unless_flags"].items()
        )
        if not cancelled:
            apply_effects(state, item["effects"], content)
        applied.append(
            {
                "option_id": item["option_id"],
                "text": item["text"],
                "effects": item["effects"],
                "cancelled": cancelled,
            }
        )
    state["delayed"] = pending
    return applied


def node_assessment(node):
    """Максимум положительных очков по каждой компетенции среди всех вариантов узла, включая
    скрытые условием: скрытый хороший вариант это упущенная возможность."""
    best = {}
    for option in node.get("options") or []:
        for code, value in (option.get("competencies") or {}).items():
            if value > 0:
                best[code] = max(best.get(code, 0), value)
    return best


def transition(scenario, content, state, source, option_id, expired):
    node = scenario["nodes"][state["node"]]
    step = {"node_id": state["node"], "option_id": option_id, "expired": expired}
    step["delayed_applied"] = tick_delayed(state, content)
    apply_effects(state, source.get("effects"), content)
    state["flags"].update(source.get("set_flags") or {})
    if option_id not in (None, CONTINUE):
        state["chosen"].append(option_id)
    verdict = (source.get("debrief") or {}).get("verdict")
    if source.get("role_step") and verdict in ("best", "ok"):
        state["role_chain"].append(source["role_step"])
    for item in source.get("delayed") or []:
        state["delayed"].append(
            {
                "due_step": state["step_no"] + item["steps"],
                "effects": item.get("effects") or {},
                "text": item.get("text", ""),
                "unless_flags": item.get("unless_flags") or {},
                "option_id": option_id,
            }
        )
    for code, value in (source.get("competencies") or {}).items():
        if value > 0:
            state["earned"][code] = state["earned"].get(code, 0) + value
    for code, value in node_assessment(node).items():
        state["assessed"][code] = state["assessed"].get(code, 0) + value
    if node.get("timer"):
        state["expired_timers" if expired else "timers_answered"] += 1
    state["step_no"] += 1
    state["node"] = source["next"]
    if scenario["nodes"][state["node"]]["type"] == "ending":
        step["delayed_applied"] += tick_delayed(state, content, force=True)
        state["status"] = "finished"
        state["outcome"] = outcome(scenario, content, state)
    return step


def apply_option(scenario, content, state, option_id):
    node = scenario["nodes"][state["node"]]
    if node["type"] == "event":
        if option_id != CONTINUE:
            raise ValueError(f"узел {state['node']} принимает только «{CONTINUE}»")
        return transition(scenario, content, state, node, CONTINUE, expired=False)
    option = next((item for item in available_options(scenario, state) if item["id"] == option_id), None)
    if option is None:
        raise ValueError(f"вариант {option_id} недоступен в узле {state['node']}")
    return transition(scenario, content, state, option, option_id, expired=False)


def apply_expire_branch(scenario, content, state):
    node = scenario["nodes"][state["node"]]
    if not node.get("timer"):
        raise ValueError(f"у узла {state['node']} нет таймера")
    return transition(scenario, content, state, node["timer"]["on_expire"], None, expired=True)


def outcome_thresholds(scenario, content):
    defaults = content.rules["outcome"]
    own = scenario.get("outcome_rules") or {}
    exemplary = dict(defaults["exemplary_if"])
    exemplary.update(own.get("exemplary_if") or {})
    incident_below = own.get("incident_if_safety_below", defaults["incident_if_safety_below"])
    return {"incident_if_safety_below": incident_below, "exemplary_if": exemplary}


def outcome(scenario, content, state):
    node = scenario["nodes"][state["node"]]
    thresholds = outcome_thresholds(scenario, content)
    forced = node.get("forced_outcome")
    if forced == "incident" or state["safety"] < thresholds["incident_if_safety_below"]:
        return "incident"
    if forced == "acceptable":
        return "acceptable"
    rule = thresholds["exemplary_if"]
    timers_ok = state["expired_timers"] == 0 or not rule.get("no_expired_timers", True)
    if state["safety"] >= rule["safety_min"] and state["loyalty"] >= rule["loyalty_min"] and timers_ok:
        return "exemplary"
    return "acceptable"


def role_chain_complete(chain):
    position = 0
    for step in chain:
        if position < len(ROLE_CHAIN) and step == ROLE_CHAIN[position]:
            position += 1
    return position == len(ROLE_CHAIN)


def enumerate_paths(scenario, content, service_class=None, limit=None):
    """Обходит все пути от старта до концовок для одного класса обслуживания и собирает
    статистику; при превышении лимита путей обход прерывается с пометкой truncated."""
    limit = limit or content.rules["analysis"]["path_limit"]
    summary = new_summary(service_class or scenario["context"]["service_class"])
    stack = [(start_state(scenario, content, service_class), [])]
    while stack:
        state, trail = stack.pop()
        if state["status"] == "finished":
            record_final(summary, scenario, state, trail)
            if summary["paths"] >= limit:
                summary["truncated"] = True
                break
            continue
        node_id = state["node"]
        if any(node_id == visited for visited, _, _ in trail):
            summary["cycle_hit"] = True
            continue
        for option_id, expired in moves_from(scenario, state, summary):
            branch = copy.deepcopy(state)
            if expired:
                apply_expire_branch(scenario, content, branch)
            else:
                apply_option(scenario, content, branch, option_id)
            stack.append((branch, trail + [(node_id, option_id, expired)]))
    finish_summary(summary, scenario)
    return summary


def new_summary(service_class):
    return {
        "service_class": service_class,
        "paths": 0,
        "truncated": False,
        "cycle_hit": False,
        "outcomes": {},
        "loyalty": {"min": None, "max": None},
        "safety": {"min": None, "max": None},
        "endings": {},
        "reachable_nodes": set(),
        "common_nodes": None,
        "corridor_share": 0.0,
        "shown": set(),
        "hidden": set(),
        "empty_nodes": set(),
        "role_chain_paths": 0,
        "potential": {},
        "timers": {},
    }


def moves_from(scenario, state, summary):
    """Возможные действия в текущем узле: continue у события, доступные варианты и истечение
    таймера у диалога; попутно отмечает показ и скрытие условных вариантов."""
    node_id = state["node"]
    node = scenario["nodes"][node_id]
    if node["type"] == "event":
        return [(CONTINUE, False)]
    options = available_options(scenario, state)
    for option in node.get("options") or []:
        if option.get("when"):
            (summary["shown"] if option in options else summary["hidden"]).add((node_id, option["id"]))
    if not options:
        summary["empty_nodes"].add(node_id)
    moves = [(option["id"], False) for option in options]
    if node.get("timer"):
        moves.append((None, True))
    return moves


def record_final(summary, scenario, state, trail):
    summary["paths"] += 1
    result = state["outcome"]
    summary["outcomes"][result] = summary["outcomes"].get(result, 0) + 1
    widen(summary["loyalty"], state["loyalty"])
    widen(summary["safety"], state["safety"])
    ending = summary["endings"].setdefault(
        state["node"],
        {
            "paths": 0,
            "outcomes": {},
            "loyalty": {"min": None, "max": None},
            "safety": {"min": None, "max": None},
        },
    )
    ending["paths"] += 1
    ending["outcomes"][result] = ending["outcomes"].get(result, 0) + 1
    widen(ending["loyalty"], state["loyalty"])
    widen(ending["safety"], state["safety"])
    nodes = {node_id for node_id, _, _ in trail} | {state["node"]}
    summary["reachable_nodes"] |= nodes
    summary["common_nodes"] = nodes if summary["common_nodes"] is None else summary["common_nodes"] & nodes
    if role_chain_complete(state["role_chain"]):
        summary["role_chain_paths"] += 1
    for code, value in state["earned"].items():
        summary["potential"][code] = max(summary["potential"].get(code, 0), value)
    final = (state["loyalty"], state["safety"], result)
    for node_id, _, expired in trail:
        if scenario["nodes"][node_id].get("timer"):
            timer = summary["timers"].setdefault(node_id, {"expired_finals": set(), "answered_finals": set()})
            timer["expired_finals" if expired else "answered_finals"].add(final)


def widen(span, value):
    span["min"] = value if span["min"] is None else min(span["min"], value)
    span["max"] = value if span["max"] is None else max(span["max"], value)


def finish_summary(summary, scenario):
    common = summary["common_nodes"] or set()
    if summary["reachable_nodes"]:
        summary["corridor_share"] = round(len(common) / len(summary["reachable_nodes"]), 2)
    summary["common_nodes"] = common


def analyze(scenario, content, limit=None):
    """Перебор для каждого класса обслуживания: условие по классу иначе было бы всегда или
    никогда показано. own это итог для родного класса сценария."""
    by_class = {code: enumerate_paths(scenario, content, code, limit) for code in content.classes}
    own = by_class[scenario["context"]["service_class"]]
    shown = set().union(*(item["shown"] for item in by_class.values()))
    hidden = set().union(*(item["hidden"] for item in by_class.values()))
    empty = set().union(*(item["empty_nodes"] for item in by_class.values()))
    return {
        "own": own,
        "by_class": by_class,
        "shown": shown,
        "hidden": hidden,
        "empty_nodes": empty,
        "role_chain_possible": any(item["role_chain_paths"] > 0 for item in by_class.values()),
        "truncated": any(item["truncated"] for item in by_class.values()),
    }
