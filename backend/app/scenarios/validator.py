"""Валидатор контента: форма DSL (schema.py), граф (достижимость, циклы, тупики, ветки
истечения), флаги, компетенции, разнонаправленность шкал, тексты, а по перебору путей
(analysis.py) условия показа, исходы, разброс шкал и ролевая цепочка. Запуск из backend:
python -m app.scenarios.validator ../content [--markdown]. Последняя строка вывода всегда
«ИТОГ: сценариев=N узлов=M ошибок=E предупреждений=W», код выхода 1 при ошибках."""

import argparse
import re
import sys
from pathlib import Path

from app.scenarios import analysis, graph, schema
from app.scenarios.findings import Checker, Finding, is_int, line_of
from app.scenarios.loader import check_references, load_content
from app.scenarios.report import format_finding, markdown_tables, outcome_summary, relative, scenario_stats
from app.scenarios.schema import all_option_ids

DASHES = (chr(0x2014), chr(0x2013))
# пометки незаконченного текста собираются из частей, чтобы проверка репозитория не ловила сам валидатор
STUB_WORDS = tuple(
    "".join(parts) for parts in (("TO", "DO"), ("FIX", "ME"), ("XX", "X"), ("place", "holder"))
)
STUB_PATTERN = re.compile(r"\b(" + "|".join(STUB_WORDS) + r")\b", re.IGNORECASE)
FULL_NAME = re.compile(
    r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.|[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:ович|евич|овна|евна|ична)\b"
)
# после этих ошибок перебор путей невозможен или бессмыслен
STRUCTURAL = set(
    "schema unknown_node cycle dead_end ending_unreachable unknown_class timer_without_expire "
    "duplicate_option_id".split()
)


def check_scenario(scenario, content, file_stem=""):
    """Все проверки одного сценария: список находок и итог перебора путей (None, если перебор
    невозможен из-за структурных ошибок)."""
    findings = []
    if not isinstance(scenario, dict) or not isinstance(scenario.get("nodes"), dict) or not scenario["nodes"]:
        findings.append(Finding("error", "schema", "сценарий должен быть словарём с непустым словарём nodes"))
        return findings, None
    checker = Checker(content, findings)
    schema.check_scenario_fields(scenario, checker, file_stem)
    check_duplicate_options(scenario, checker)
    for node_id, node in scenario["nodes"].items():
        schema.check_node(node_id, node, scenario, checker)
    checker.node = checker.option = None
    check_texts(scenario, checker)
    check_competencies(scenario, checker)
    check_scale_directions(scenario, checker)
    check_flags(scenario, checker)
    check_graph(scenario, checker)
    if any(item.code in STRUCTURAL for item in findings):
        return findings, None
    return findings, check_paths(scenario, checker)


def validate_scenario(scenario, content, file_stem=""):
    return check_scenario(scenario, content, file_stem)[0]


def check_duplicate_options(scenario, checker):
    seen = set()
    for option_id in all_option_ids(scenario):
        if option_id in seen:
            checker.error(
                "duplicate_option_id", f"id варианта «{option_id}» встречается дважды", scenario["nodes"]
            )
        seen.add(option_id)


def check_texts(scenario, checker):
    for text, node_id, option_id, where in iter_texts(scenario):
        checker.node, checker.option = node_id, option_id
        if any(dash in text for dash in DASHES):
            checker.error(
                "dash_in_text", "тире в тексте: замените запятой, двоеточием или словом «это»", where
            )
        if STUB_PATTERN.search(text):
            checker.error("stub_in_text", "в тексте пометка незаконченной работы", where)
        if FULL_NAME.search(text):
            checker.error(
                "full_name_in_text", "в тексте похоже на ФИО; пассажиров называем местом и приметой", where
            )
    checker.node = checker.option = None


def iter_texts(scenario):
    """Все строки сценария с узлом и вариантом, внутри которых они встретились."""
    yield from walk_texts(scenario, scenario, None, None, None)


def walk_texts(scenario, value, node_id, option_id, where):
    if isinstance(value, dict):
        where = value if line_of(value) else where
        for key, item in value.items():
            if key == "nodes" and value is scenario and isinstance(item, dict):
                for inner_id, node in item.items():
                    yield from walk_texts(scenario, node, inner_id, None, node)
            elif key == "options" and isinstance(item, list):
                for option in item:
                    inner = option.get("id") if isinstance(option, dict) else None
                    yield from walk_texts(scenario, option, node_id, inner, option)
            else:
                yield from walk_texts(scenario, item, node_id, option_id, where)
    elif isinstance(value, list):
        for item in value:
            yield from walk_texts(scenario, item, node_id, option_id, where)
    elif isinstance(value, str):
        yield value, node_id, option_id, where


def iter_actions(scenario):
    """Варианты и ветки истечения: всё, у чего есть effects и competencies."""
    for node_id, node in scenario["nodes"].items():
        if not isinstance(node, dict):
            continue
        for option in node.get("options") or []:
            if isinstance(option, dict):
                yield node_id, option.get("id"), option
        timer = node.get("timer")
        if isinstance(timer, dict) and isinstance(timer.get("on_expire"), dict):
            yield node_id, None, timer["on_expire"]


def check_competencies(scenario, checker):
    known = {item.get("code") for item in checker.content.competencies if isinstance(item, dict)}
    declared = scenario.get("competencies") if isinstance(scenario.get("competencies"), list) else []
    for code in declared:
        if code not in known:
            checker.error("unknown_competency", f"компетенции «{code}» нет в competencies.yaml", scenario)
    used = {}
    for node_id, option_id, action in iter_actions(scenario):
        for code in (
            (action.get("competencies") or {}) if isinstance(action.get("competencies"), dict) else ()
        ):
            used.setdefault(code, (node_id, option_id, action))
    for code, (node_id, option_id, action) in used.items():
        checker.node, checker.option = node_id, option_id
        if code not in known:
            checker.error("unknown_competency", f"компетенции «{code}» нет в competencies.yaml", action)
        elif code not in declared:
            checker.error("competency_not_declared", f"компетенция «{code}» не заявлена в сценарии", action)
    checker.node = checker.option = None
    for code in declared:
        if code in known and code not in used:
            checker.error(
                "competency_unused", f"заявленная компетенция «{code}» не встречается в эффектах", scenario
            )


def check_scale_directions(scenario, checker):
    diverging = loyalty_only = safety_only = False
    for _, _, action in iter_actions(scenario):
        effects = action.get("effects") if isinstance(action.get("effects"), dict) else {}
        loyalty, safety = effects.get("loyalty", 0), effects.get("safety", 0)
        if not is_int(loyalty) or not is_int(safety):
            continue
        diverging |= loyalty * safety < 0
        loyalty_only |= loyalty != 0 and safety == 0
        safety_only |= safety != 0 and loyalty == 0
    if not diverging:
        checker.error("no_diverging_option", "нет варианта с разнонаправленным влиянием на шкалы", scenario)
    if not loyalty_only:
        checker.error("no_loyalty_only_option", "нет варианта, который меняет только лояльность", scenario)
    if not safety_only:
        checker.error("no_safety_only_option", "нет варианта, который меняет только безопасность", scenario)


def check_flags(scenario, checker):
    """Флаг, который нигде не читается, декоративен: это ошибка, а не предупреждение."""
    set_flags = {}
    read_flags = {}
    unless_flags = {}
    start = scenario.get("start") if isinstance(scenario.get("start"), dict) else {}
    for name in start.get("flags") or {}:
        set_flags.setdefault(name, (None, None, start))
    for node_id, node in scenario["nodes"].items():
        if isinstance(node, dict) and isinstance(node.get("set_flags"), dict):
            for name in node["set_flags"]:
                set_flags.setdefault(name, (node_id, None, node))
    for node_id, option_id, action in iter_actions(scenario):
        for name in action.get("set_flags") or {} if isinstance(action.get("set_flags"), dict) else ():
            set_flags.setdefault(name, (node_id, option_id, action))
        when = action.get("when") if isinstance(action.get("when"), dict) else {}
        names = list(when.get("flags_all") or {}) if isinstance(when.get("flags_all"), dict) else []
        names += list(when.get("flags_none") or []) if isinstance(when.get("flags_none"), list) else []
        for name in names:
            read_flags.setdefault(name, (node_id, option_id, action))
        for item in action.get("delayed") or [] if isinstance(action.get("delayed"), list) else ():
            if isinstance(item, dict) and isinstance(item.get("unless_flags"), dict):
                for name in item["unless_flags"]:
                    unless_flags.setdefault(name, (node_id, option_id, item))
    for name, (node_id, option_id, where) in set_flags.items():
        if name not in read_flags and name not in unless_flags:
            checker.node, checker.option = node_id, option_id
            checker.error("flag_never_read", f"флаг «{name}» выставляется, но нигде не читается", where)
    for name, (node_id, option_id, where) in read_flags.items():
        if name not in set_flags:
            checker.node, checker.option = node_id, option_id
            checker.warning("flag_never_set", f"флаг «{name}» читается, но нигде не выставляется", where)
    for name, (node_id, option_id, where) in unless_flags.items():
        if name not in set_flags:
            checker.node, checker.option = node_id, option_id
            checker.error(
                "unless_flag_never_set", f"флаг «{name}» из unless_flags нигде не выставляется", where
            )
    checker.node = checker.option = None


def check_graph(scenario, checker):
    nodes = scenario["nodes"]
    edges = graph.edges_of(scenario)
    start = (scenario.get("start") or {}).get("node")
    if start not in nodes:
        checker.error("unknown_node", f"стартового узла «{start}» нет", scenario.get("start"))
    for item in edges:
        # переход без next уже отмечен как dead_end или ошибка формы
        if item["to"] is not None and item["to"] not in nodes:
            checker.node, checker.option = item["from"], item["option_id"]
            checker.error(
                "unknown_node", f"переход в несуществующий узел «{item['to']}»", nodes[item["from"]]
            )
    checker.node = checker.option = None
    if start not in nodes:
        return
    depth = graph.reachable_nodes(scenario, edges)
    for node_id in nodes:
        if node_id not in depth:
            checker.node = node_id
            checker.error("unreachable_node", "узел недостижим от старта", nodes[node_id])
    checker.node = None
    if not any(
        isinstance(nodes[node_id], dict) and nodes[node_id].get("type") == "ending" for node_id in depth
    ):
        checker.error("ending_unreachable", "от старта не достижима ни одна концовка", scenario)
    cycle = graph.find_cycle(scenario, edges)
    if cycle:
        checker.error(
            "cycle", "цикл " + " -> ".join(cycle) + ": повтор моделируется отдельным узлом", nodes[cycle[0]]
        )
    check_expire_branches(scenario, edges, checker)


def check_expire_branches(scenario, edges, checker):
    """Ветка истечения ведёт в узел, в который иначе не попасть, и отличается от вариантов."""
    for node_id, node in scenario["nodes"].items():
        timer = node.get("timer") if isinstance(node, dict) else None
        on_expire = timer.get("on_expire") if isinstance(timer, dict) else None
        if not isinstance(on_expire, dict) or on_expire.get("next") not in scenario["nodes"]:
            continue
        checker.node = node_id
        target = on_expire["next"]
        others = [
            item
            for item in edges
            if item["to"] == target and not (item["from"] == node_id and item["kind"] == "expire")
        ]
        if others:
            sources = ", ".join(f"{item['from']} ({item['label']})" for item in others)
            checker.error(
                "expire_node_reachable_by_option",
                f"в узел истечения «{target}» ведут и другие переходы: {sources}",
                on_expire,
            )
        for option in node.get("options") or []:
            if not isinstance(option, dict):
                continue
            same_effects = effects_pair(option.get("effects")) == effects_pair(on_expire.get("effects"))
            if option.get("next") == target and same_effects:
                checker.option = option.get("id")
                checker.error(
                    "expire_branch_equals_option",
                    "истечение повторяет вариант: тот же узел и те же эффекты",
                    on_expire,
                )
    checker.node = checker.option = None


def effects_pair(effects):
    effects = effects if isinstance(effects, dict) else {}
    return effects.get("loyalty", 0), effects.get("safety", 0)


def check_paths(scenario, checker):
    result = analysis.analyze(scenario, checker.content)
    own = result["own"]
    settings = checker.content.rules["analysis"]
    if result["truncated"]:
        checker.error(
            "path_limit_exceeded", f"путей больше {settings['path_limit']}: упростите поздние узлы", scenario
        )
    elif own["paths"] > settings["many_paths"]:
        checker.warning(
            "many_paths", f"путей {own['paths']}: сценарий тяжело перебирать и проходить", scenario
        )
    for node_id, option_id, action in iter_actions(scenario):
        if option_id is None or not action.get("when"):
            continue
        checker.node, checker.option = node_id, option_id
        if (node_id, option_id) not in result["shown"]:
            checker.error("condition_never_shown", "условие варианта не выполняется ни на одном пути", action)
        if (node_id, option_id) not in result["hidden"]:
            checker.error(
                "condition_always_shown", "условие варианта выполняется на всех путях: оно не нужно", action
            )
    for node_id in sorted(result["empty_nodes"]):
        checker.node, checker.option = node_id, None
        checker.error(
            "node_without_options_on_path",
            "на одном из путей узел остаётся без вариантов",
            scenario["nodes"][node_id],
        )
    check_expire_cost(scenario, own, checker)
    checker.node = checker.option = None
    if len(own["outcomes"]) < settings["min_outcomes"]:
        checker.error(
            "single_outcome",
            f"достижимые исходы: {outcome_summary(own['outcomes'])}; нужно не меньше двух",
            scenario,
        )
    for scale in ("loyalty", "safety"):
        spread = own[scale]["max"] - own[scale]["min"] if own["paths"] else 0
        if spread < settings["min_scale_spread"]:
            title = "лояльности" if scale == "loyalty" else "безопасности"
            need = settings["min_scale_spread"]
            checker.error(
                "low_scale_spread",
                f"разброс финальной {title} по путям {spread}, нужно не меньше {need}",
                scenario,
            )
    if scenario.get("role_model") is True and not result["role_chain_possible"]:
        checker.error(
            "role_chain_impossible",
            "role_model true, но нет пути с цепочкой acknowledge, rule, solution, assure",
            scenario,
        )
    if own["corridor_share"] > settings["corridor_share"]:
        checker.warning(
            "corridor",
            f"доля узлов, общих для всех путей, {own['corridor_share']}: сценарий слишком линеен",
            scenario,
        )
    return result


def check_expire_cost(scenario, own, checker):
    """Таймер не декоративен, только если истечение закрывает лучший финал узла: лучший путь
    через истечение обязан быть хуже лучшего пути через любой вариант того же узла."""
    for node_id, timer in sorted(own["timers"].items()):
        if not timer["expired_finals"] or not timer["answered_finals"]:
            continue
        expired = analysis.final_key(analysis.best_final(timer["expired_finals"]))
        answered = analysis.final_key(analysis.best_final(timer["answered_finals"]))
        if expired >= answered:
            checker.node, checker.option = node_id, None
            checker.error(
                "expire_branch_harmless",
                "истечение таймера не ухудшает лучший достижимый финал: таймер ничего не решает",
                scenario["nodes"][node_id]["timer"]["on_expire"],
            )


def validate_content(content):
    """Отчёт по всему контенту: ошибки чтения, справочники, находки и перебор по сценариям."""
    report = {"reference_problems": check_references(content), "scenarios": {}, "invalid": []}
    rules_ok = not any(problem.startswith("rules.yaml") for problem in report["reference_problems"])
    for scenario_id, scenario in content.scenarios.items():
        path = content.files[scenario_id]
        if rules_ok:
            findings, result = check_scenario(scenario, content, path.stem)
        else:
            findings, result = (
                [Finding("error", "rules_broken", "сценарий не проверялся: сломан rules.yaml")],
                None,
            )
        valid = not any(item.severity == "error" for item in findings)
        nodes = len(scenario["nodes"]) if valid else 0
        report["scenarios"][scenario_id] = {
            "file": path,
            "findings": findings,
            "analysis": result,
            "nodes": nodes,
            "valid": valid,
        }
        if not valid:
            report["invalid"].append(scenario_id)
    scenario_findings = [item for entry in report["scenarios"].values() for item in entry["findings"]]
    report["errors"] = (
        len(content.errors)
        + len(report["reference_problems"])
        + sum(item.severity == "error" for item in scenario_findings)
    )
    report["warnings"] = sum(item.severity == "warning" for item in scenario_findings)
    valid_count = sum(entry["valid"] for entry in report["scenarios"].values())
    node_count = sum(entry["nodes"] for entry in report["scenarios"].values())
    counts = f"ошибок={report['errors']} предупреждений={report['warnings']}"
    report["summary"] = f"ИТОГ: сценариев={valid_count} узлов={node_count} {counts}"
    return report


def load_validated(content_dir):
    """Контент только с валидными сценариями и отчёт: так сервер читает папку content при
    старте и при перечитывании, сломанный файл не попадает в каталог."""
    content = load_content(content_dir)
    report = validate_content(content)
    for scenario_id in report["invalid"]:
        content.scenarios.pop(scenario_id)
        content.files.pop(scenario_id)
    return content, report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Проверка сценариев и справочников тренажёра")
    parser.add_argument("content_dir", nargs="?", default="../content", help="папка content")
    parser.add_argument("--markdown", action="store_true", help="сводные таблицы для документации")
    args = parser.parse_args(argv)
    content = load_content(Path(args.content_dir))
    report = validate_content(content)
    for error in content.errors:
        print(f"{relative(error['file'])}:{error['line']}: ошибка {error['code']}: {error['message']}")
    for problem in report["reference_problems"]:
        print(f"{relative(Path(args.content_dir))}: ошибка reference: {problem}")
    for scenario_id, entry in report["scenarios"].items():
        for finding in entry["findings"]:
            print(format_finding(entry["file"], finding))
        if entry["valid"] and entry["analysis"] and not args.markdown:
            print(scenario_stats(scenario_id, content.scenarios[scenario_id], entry["analysis"]))
    if args.markdown:
        print(markdown_tables(content, report))
    print(report["summary"])
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
