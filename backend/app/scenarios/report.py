"""Текстовый вывод валидатора: строки «файл:строка: ошибка код: сообщение», сводка по сценарию
и таблицы Markdown для docs/scenarios.md. Здесь нет проверок, только форматирование."""

# относительный путь через «..» (валидатор запускается из backend для ../content) у pathlib не
# строится, поэтому единственное место с os.path
import os

OUTCOME_TITLES = {"exemplary": "образцово", "acceptable": "приемлемо", "incident": "инцидент"}
SEVERITY_TITLES = {"error": "ошибка", "warning": "предупреждение"}


def relative(path):
    try:
        return os.path.relpath(path).replace(os.sep, "/")
    except ValueError:
        # другой диск Windows: относительного пути нет
        return str(path).replace(os.sep, "/")


def format_finding(path, finding):
    place = ""
    if finding.node:
        place = f"узел {finding.node}" + (f", вариант {finding.option}" if finding.option else "") + ": "
    severity = SEVERITY_TITLES[finding.severity]
    return f"{relative(path)}:{finding.line}: {severity} {finding.code}: {place}{finding.message}"


def outcome_summary(outcomes):
    return ", ".join(f"{OUTCOME_TITLES.get(key, key)} {count}" for key, count in sorted(outcomes.items()))


def span(values):
    return f"{values['min']}..{values['max']}"


def timer_count(scenario):
    return sum(1 for node in scenario["nodes"].values() if node.get("timer"))


def scenario_stats(scenario_id, scenario, result):
    own = result["own"]
    return (
        f"{scenario_id}: узлов={len(scenario['nodes'])} таймеров={timer_count(scenario)} "
        f"путей={own['paths']} исходы: {outcome_summary(own['outcomes'])}; "
        f"лояльность {span(own['loyalty'])}, безопасность {span(own['safety'])}"
    )


def markdown_tables(content, report):
    """Две таблицы: по сценариям и по концовкам с диапазонами финальных шкал."""
    lines = [
        "| Сценарий | Название | Класс | Узлов | Таймеров | Путей | Исходы | Лояльность | Безопасность |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    endings = [
        "",
        "| Сценарий | Концовка | Путей | Исходы | Лояльность | Безопасность |",
        "|---|---|---|---|---|---|",
    ]
    for scenario_id, entry in report["scenarios"].items():
        if not entry["valid"]:
            continue
        scenario = content.scenarios[scenario_id]
        own = entry["analysis"]["own"]
        class_title = content.classes[scenario["context"]["service_class"]]["title"].lower()
        lines.append(
            f"| {scenario_id} | {scenario['title']} | {class_title} | {len(scenario['nodes'])} | "
            f"{timer_count(scenario)} | {own['paths']} | {outcome_summary(own['outcomes'])} | "
            f"{span(own['loyalty'])} | {span(own['safety'])} |"
        )
        for ending_id, ending in sorted(own["endings"].items()):
            outcomes = outcome_summary(ending["outcomes"])
            endings.append(
                f"| {scenario_id} | {ending_id} | {ending['paths']} | {outcomes} | "
                f"{span(ending['loyalty'])} | {span(ending['safety'])} |"
            )
    return "\n".join(lines + endings)
