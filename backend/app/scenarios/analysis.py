"""Перебор путей сценария теми же функциями движка, что ведут прохождение на сервере, но без
часов: по итогам валидатор судит о достижимости исходов, условных вариантах, разбросе шкал,
цене истечения таймеров, узлах без выбора и нагрузке чтения, а карта сценария берёт число
путей. Итог целиком состоит из чисел, строк, списков и словарей, чтобы уходить в JSON как есть."""

import copy

from app.scenarios.engine import (
    CONTINUE,
    OUTCOMES,
    apply_expire_branch,
    apply_option,
    available_options,
    role_chain_complete,
    start_state,
)


def enumerate_paths(scenario, content, service_class=None, limit=None):
    """Обходит все пути от старта до концовок для одного класса обслуживания и собирает
    статистику; при превышении лимита путей обход прерывается с пометкой truncated."""
    limit = limit or content.rules["analysis"]["path_limit"]
    summary = new_summary(service_class or scenario["context"]["service_class"])
    stack = [start_state(scenario, content, service_class)]
    while stack:
        state = stack.pop()
        if state["status"] == "finished":
            record_final(summary, scenario, state)
            if summary["paths"] >= limit:
                summary["truncated"] = True
                break
            continue
        node_id = state["node"]
        if any(step["node_id"] == node_id for step in state["steps"]):
            # повторный вход в узел бывает только у непроверенного сценария с циклом: путь обрывается
            continue
        for option_id, expired in moves_from(scenario, state, summary):
            branch = copy.deepcopy(state)
            if expired:
                apply_expire_branch(scenario, content, branch)
            else:
                apply_option(scenario, content, branch, option_id)
            stack.append(branch)
    finish_summary(summary)
    return summary


def new_summary(service_class):
    return {
        "service_class": service_class,
        "paths": 0,
        "truncated": False,
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
        "single_option_nodes": set(),
        "option_chars": {},
        "role_chain_paths": 0,
        "potential": {},
        "delayed_cancelled": set(),
        "timers": {},
    }


def moves_from(scenario, state, summary):
    """Возможные действия в текущем узле: continue у события, доступные варианты и истечение
    таймера у диалога; попутно отмечает показ и скрытие условных вариантов, узлы без выбора и
    самый длинный набор видимых вариантов."""
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
    elif len(options) == 1:
        summary["single_option_nodes"].add(node_id)
    chars = sum(len(option.get("text") or "") for option in options)
    summary["option_chars"][node_id] = max(summary["option_chars"].get(node_id, 0), chars)
    moves = [(option["id"], False) for option in options]
    if node.get("timer"):
        moves.append((None, True))
    return moves


def record_final(summary, scenario, state):
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
    nodes = {step["node_id"] for step in state["steps"]} | {state["node"]}
    summary["reachable_nodes"] |= nodes
    summary["common_nodes"] = nodes if summary["common_nodes"] is None else summary["common_nodes"] & nodes
    if role_chain_complete(state["role_chain"]):
        summary["role_chain_paths"] += 1
    for code, value in state["earned"].items():
        summary["potential"][code] = max(summary["potential"].get(code, 0), value)
    final = (result, state["loyalty"], state["safety"])
    for step in state["steps"]:
        for item in step["delayed_applied"]:
            if item["cancelled"]:
                summary["delayed_cancelled"].add(item["option_id"])
        if step["timer_seconds"]:
            timer = summary["timers"].setdefault(
                step["node_id"], {"expired_finals": set(), "answered_finals": set()}
            )
            timer["expired_finals" if step["expired"] else "answered_finals"].add(final)


def widen(span, value):
    span["min"] = value if span["min"] is None else min(span["min"], value)
    span["max"] = value if span["max"] is None else max(span["max"], value)


def finish_summary(summary):
    common = summary["common_nodes"] or set()
    if summary["reachable_nodes"]:
        summary["corridor_share"] = round(len(common) / len(summary["reachable_nodes"]), 2)
    summary["common_nodes"] = common
    # множества нужны только при обходе; наружу уходят списки, которые переживают json.dumps
    for key in ("reachable_nodes", "common_nodes", "shown", "hidden", "empty_nodes", "single_option_nodes"):
        summary[key] = sorted(summary[key])
    summary["delayed_cancelled"] = sorted(summary["delayed_cancelled"])
    for timer in summary["timers"].values():
        timer["expired_finals"] = sorted(timer["expired_finals"])
        timer["answered_finals"] = sorted(timer["answered_finals"])


def final_key(final):
    """Порядок финалов (исход, лояльность, безопасность): сначала исход, потом сумма шкал."""
    result, loyalty, safety = final
    return (OUTCOMES.index(result), loyalty + safety)


def best_final(finals):
    return max(finals, key=final_key)


def analyze(scenario, content, limit=None):
    """Перебор для каждого класса обслуживания: условие по классу иначе было бы всегда или
    никогда показано. own это итог для родного класса сценария."""
    by_class = {code: enumerate_paths(scenario, content, code, limit) for code in content.classes}
    own = by_class[scenario["context"]["service_class"]]
    option_chars = {}
    for item in by_class.values():
        for node_id, chars in item["option_chars"].items():
            option_chars[node_id] = max(option_chars.get(node_id, 0), chars)
    return {
        "own": own,
        "by_class": by_class,
        "shown": union_of(by_class, "shown"),
        "hidden": union_of(by_class, "hidden"),
        "empty_nodes": union_of(by_class, "empty_nodes"),
        "single_option_nodes": union_of(by_class, "single_option_nodes"),
        "delayed_cancelled": union_of(by_class, "delayed_cancelled"),
        "option_chars": option_chars,
        "role_chain_possible": any(item["role_chain_paths"] > 0 for item in by_class.values()),
        "truncated": any(item["truncated"] for item in by_class.values()),
    }


def union_of(by_class, key):
    return sorted(set().union(*(item[key] for item in by_class.values())))
