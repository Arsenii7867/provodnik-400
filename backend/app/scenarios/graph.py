"""Граф сценария: рёбра по вариантам, переходам событий и веткам истечения, достижимость и
поиск циклов для валидатора, а для экрана «Как устроен сценарий» узлы с глубиной, экспорт в
Mermaid и фрагмент YAML стартового узла. Данные берутся из сценария как есть."""

from collections import deque

LABEL_LENGTH = 60
EXCERPT_LINES = 40


def edges_of(scenario):
    """Все переходы сценария: словари from, to, kind (option, next, expire), option_id, label,
    conditional. Переходы в несуществующие узлы тоже возвращаются: их ловит валидатор."""
    edges = []
    for node_id, node in scenario["nodes"].items():
        if not isinstance(node, dict):
            continue
        for option in node.get("options") or []:
            if isinstance(option, dict):
                edges.append(
                    edge(node_id, option.get("next"), "option", option.get("id"), bool(option.get("when")))
                )
        if node.get("type") == "event":
            edges.append(edge(node_id, node.get("next"), "next", None, False))
        on_expire = (
            (node.get("timer") or {}).get("on_expire") if isinstance(node.get("timer"), dict) else None
        )
        if isinstance(on_expire, dict):
            edges.append(edge(node_id, on_expire.get("next"), "expire", None, False))
    return edges


def edge(source, target, kind, option_id, conditional):
    label = option_id or ("истечение" if kind == "expire" else "далее")
    return {
        "from": source,
        "to": target,
        "kind": kind,
        "option_id": option_id,
        "label": label,
        "conditional": conditional,
    }


def reachable_nodes(scenario, edges):
    """Узлы, достижимые от стартового по любым рёбрам, с глубиной (длиной кратчайшего пути)."""
    start = scenario["start"]["node"]
    if start not in scenario["nodes"]:
        return {}
    depth = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for item in edges:
            if item["from"] == current and item["to"] in scenario["nodes"] and item["to"] not in depth:
                depth[item["to"]] = depth[current] + 1
                queue.append(item["to"])
    return depth


def find_cycle(scenario, edges):
    """Возвращает список узлов первого найденного цикла или пустой список, если граф это DAG."""
    successors = {}
    for item in edges:
        if item["to"] in scenario["nodes"]:
            successors.setdefault(item["from"], []).append(item["to"])
    state = {}
    stack = []

    def visit(node_id):
        state[node_id] = "active"
        stack.append(node_id)
        for target in successors.get(node_id, []):
            if state.get(target) == "active":
                return stack[stack.index(target) :] + [target]
            if target not in state:
                found = visit(target)
                if found:
                    return found
        stack.pop()
        state[node_id] = "done"
        return []

    for node_id in scenario["nodes"]:
        if node_id not in state:
            found = visit(node_id)
            if found:
                return found
    return []


def build_graph(scenario, analysis, source_text=None):
    """Данные для карты сценария: узлы, рёбра, число путей и исходов для родного класса,
    диапазоны финальных шкал, Mermaid и фрагмент YAML стартового узла."""
    edges = edges_of(scenario)
    depth = reachable_nodes(scenario, edges)
    own = analysis["own"]
    endings = own.get("endings") or {}
    nodes = [
        graph_node(node_id, node, depth, endings.get(node_id)) for node_id, node in scenario["nodes"].items()
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "paths": own["paths"],
        "outcomes": own["outcomes"],
        "scale_ranges": {"loyalty": own["loyalty"], "safety": own["safety"]},
        "mermaid": mermaid(scenario, nodes, edges),
        "yaml_excerpt": yaml_excerpt(scenario, source_text or ""),
    }


def graph_node(node_id, node, depth, ending=None):
    text = node.get("title") if node.get("type") == "ending" else node.get("text", "")
    label = " ".join(str(text).split())
    if len(label) > LABEL_LENGTH:
        label = label[: LABEL_LENGTH - 1].rstrip() + "…"
    timer = node.get("timer") or {}
    return {
        "id": node_id,
        "type": node.get("type"),
        "label": label,
        "timer_seconds": timer.get("seconds"),
        "depth": depth.get(node_id),
        # у концовки исходы путей через неё из перебора: карта красит её по преобладающему
        "outcomes": dict((ending or {}).get("outcomes") or {}),
    }


def mermaid(scenario, nodes, edges):
    lines = ["flowchart TD"]
    for node in nodes:
        label = node["label"].replace('"', "'")
        shape = f'[["{label}"]]' if node["type"] == "ending" else f'["{label}"]'
        lines.append(f"  {node['id']}{shape}")
    for item in edges:
        if item["to"] not in scenario["nodes"]:
            continue
        arrow = "-.->" if item["kind"] == "expire" else "-->"
        label = item["label"] + (" (условие)" if item["conditional"] else "")
        lines.append(f"  {item['from']} {arrow}|{label}| {item['to']}")
    return "\n".join(lines)


def yaml_excerpt(scenario, source_text):
    """Строки стартового узла из исходного файла: жюри видит живой YAML, а не пересказ."""
    start = scenario["start"]["node"]
    lines = source_text.splitlines()
    key_line = next((index for index, line in enumerate(lines) if line.strip() == f"{start}:"), None)
    if key_line is None:
        return ""
    indent = len(lines[key_line]) - len(lines[key_line].lstrip())
    excerpt = [lines[key_line]]
    for line in lines[key_line + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        excerpt.append(line)
        if len(excerpt) >= EXCERPT_LINES:
            break
    return "\n".join(excerpt)
