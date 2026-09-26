"""Движок прохождения: чистые функции над словарём состояния, без БД и веб-фреймворка.
Ядро без времени (старт, доступные варианты, эффекты, выбор, ветка истечения, отложенные
последствия, исход) делят перебор путей в analysis.py и сервер; слой со временем (start,
apply_choice, apply_expiry) хранит дедлайн моментом времени и решает, был ли выбор поздним.
Все числа приходят из content: classes.yaml, rules.yaml и outcome_rules сценария."""

import math
from datetime import timedelta

from app.scenarios import rules as rulebook

ROLE_CHAIN = ("acknowledge", "rule", "solution", "assure")
CONTINUE = "continue"
# исходы от худшего к лучшему: по этому порядку сравниваются финалы путей
OUTCOMES = ("incident", "acceptable", "exemplary")


class EngineError(Exception):
    """Отказ движка с машинным кодом; сервис отвечает 409 с тем же кодом."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


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
        "steps": [],
        "node_entered_at": None,
        "deadline_at": None,
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


def apply_delayed(state, content, force=False):
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


def timer_seconds(node, service_class):
    timer = node.get("timer")
    if not timer:
        return None
    by_class = timer.get("seconds_by_class") or {}
    return by_class.get(service_class, timer.get("seconds"))


def transition(scenario, content, state, source, option_id, expired):
    """Один шаг прохождения: source это вариант, узел-событие или ветка on_expire."""
    node = scenario["nodes"][state["node"]]
    step = {
        "step_no": state["step_no"] + 1,
        "node_id": state["node"],
        "option_id": option_id,
        "expired": expired,
        "effects": dict(source.get("effects") or {}),
        "competencies": dict(source.get("competencies") or {}),
        "loyalty_before": state["loyalty"],
        "safety_before": state["safety"],
        "timer_seconds": timer_seconds(node, state["service_class"]),
    }
    step["delayed_applied"] = apply_delayed(state, content)
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
        # невыполненное к концовке обещание остаётся невыполненным: остаток очереди применяется здесь
        step["delayed_applied"] += apply_delayed(state, content, force=True)
        state["status"] = "finished"
        state["outcome"] = outcome(scenario, content, state)
    step["loyalty_after"] = state["loyalty"]
    step["safety_after"] = state["safety"]
    step["next_node"] = state["node"]
    state["steps"].append(step)
    return step


def apply_option(scenario, content, state, option_id):
    node = scenario["nodes"][state["node"]]
    if node["type"] == "event":
        if option_id != CONTINUE:
            raise EngineError("option_unavailable", f"узел {state['node']} принимает только «{CONTINUE}»")
        return transition(scenario, content, state, node, CONTINUE, expired=False)
    option = next((item for item in available_options(scenario, state) if item["id"] == option_id), None)
    if option is None:
        raise EngineError("option_unavailable", f"вариант {option_id} недоступен в узле {state['node']}")
    return transition(scenario, content, state, option, option_id, expired=False)


def apply_expire_branch(scenario, content, state):
    node = scenario["nodes"][state["node"]]
    if not node.get("timer"):
        raise EngineError("no_timer", f"у узла {state['node']} нет таймера")
    return transition(scenario, content, state, node["timer"]["on_expire"], None, expired=True)


def outcome(scenario, content, state):
    node = scenario["nodes"][state["node"]]
    thresholds = rulebook.outcome_thresholds(scenario, content.rules)
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


def chain_position(chain):
    position = 0
    for step in chain:
        if position < len(ROLE_CHAIN) and step == ROLE_CHAIN[position]:
            position += 1
    return position


def role_chain_complete(chain):
    return chain_position(chain) == len(ROLE_CHAIN)


def role_chain_progress(state):
    position = chain_position(state["role_chain"])
    return {
        "steps": list(ROLE_CHAIN[:position]),
        "next_expected": ROLE_CHAIN[position] if position < len(ROLE_CHAIN) else None,
        "complete": position == len(ROLE_CHAIN),
    }


def start(scenario, content, now, service_class=None):
    state = start_state(scenario, content, service_class)
    enter_node(scenario, state, now)
    return state


def enter_node(scenario, state, now):
    # дедлайн хранится моментом времени, а не остатком: переживает перезапуск сервера и не зависит от клиента
    seconds = timer_seconds(scenario["nodes"][state["node"]], state["service_class"])
    state["node_entered_at"] = now
    state["deadline_at"] = now + timedelta(seconds=seconds) if seconds else None


def require_active(state):
    if state["status"] != "active":
        raise EngineError("run_not_active", "прохождение уже завершено")


def apply_choice(scenario, content, state, option_id, now, grace_seconds=0.0):
    """Выбор после дедлайна с допуском не отклоняется, а трактуется как истечение: клиент мог
    нажать на последней секунде, но решает время сервера."""
    require_active(state)
    deadline = state["deadline_at"]
    if deadline is not None and now > deadline + timedelta(seconds=grace_seconds):
        return apply_expiry(scenario, content, state, now, grace_seconds)
    step = apply_option(scenario, content, state, option_id)
    return finish_step(scenario, state, step, now)


def apply_expiry(scenario, content, state, now, grace_seconds=0.0):
    require_active(state)
    if state["deadline_at"] is None:
        raise EngineError("no_timer", f"у узла {state['node']} нет таймера")
    if now < state["deadline_at"] - timedelta(seconds=grace_seconds):
        raise EngineError("too_early", "таймер ещё идёт: истечение принимается после дедлайна")
    step = apply_expire_branch(scenario, content, state)
    return finish_step(scenario, state, step, now)


def finish_step(scenario, state, step, now):
    step["answered_in_seconds"] = round((now - state["node_entered_at"]).total_seconds(), 1)
    enter_node(scenario, state, now)
    return state, step
