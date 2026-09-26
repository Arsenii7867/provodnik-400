"""Проверки одного сценария без перебора путей: тексты (тире, пометки незаконченной работы, ФИО), реплика
пассажира и повторы вариантов, карточки-источники, компетенции, разнонаправленность шкал и
флаги. Валидатор вызывает их до проверок графа и путей; тесты содержательности берут отсюда
обход текстов."""

import re

from app.scenarios.findings import is_int, line_of

DASHES = (chr(0x2014), chr(0x2013))
# пометки незаконченного текста собираются из частей, чтобы проверка репозитория не ловила сам валидатор
STUB_WORDS = tuple(
    "".join(parts) for parts in (("TO", "DO"), ("FIX", "ME"), ("XX", "X"), ("place", "holder"))
)
STUB_PATTERN = re.compile(r"\b(" + "|".join(STUB_WORDS) + r")\b", re.IGNORECASE)
FULL_NAME = re.compile(
    r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.|[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:ович|евич|овна|евна|ична)\b"
)
SITUATION_KEY = re.compile(r"^sit_(\d+)$")


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


def check_passenger_voice(scenario, checker):
    """Сценарий без единой реплики пассажира читается как инструкция, а не как ситуация."""
    nodes = scenario["nodes"].values()
    if not any(isinstance(node, dict) and is_text_value(node.get("passenger_says")) for node in nodes):
        checker.error("no_passenger_says", "ни в одном узле нет реплики пассажира passenger_says", scenario)
    seen = {}
    for node_id, option_id, action in iter_actions(scenario):
        text = action.get("text")
        if option_id is None or not is_text_value(text):
            continue
        if text in seen:
            checker.node, checker.option = node_id, option_id
            checker.warning(
                "duplicate_option_text", f"текст варианта повторяет вариант «{seen[text]}»", action
            )
        seen.setdefault(text, option_id)
    checker.node = checker.option = None


def is_text_value(value):
    return isinstance(value, str) and bool(value.strip())


def check_sources(scenario, checker):
    """Карточки из source_situations это источник сценария: у каждой есть запись в refs.yaml
    и хотя бы один разбор её цитирует, а цитируемые карточки перечислены в источниках."""
    sources = scenario.get("source_situations")
    if not isinstance(sources, list) or any(not is_int(item) for item in sources):
        return
    cited = {}
    for refs, node_id, option_id, where in iter_ref_lists(scenario):
        for key in refs:
            match = SITUATION_KEY.match(str(key))
            if match:
                cited.setdefault(int(match.group(1)), (node_id, option_id, where))
    for number in sources:
        key = f"sit_{number}"
        if key not in checker.content.refs:
            checker.error(
                "source_situation_unknown",
                f"карточки {number} из source_situations нет в refs.yaml",
                scenario,
            )
        elif number not in cited:
            checker.error(
                "source_situation_uncited",
                f"карточку {number} из source_situations не цитирует ни один разбор",
                scenario,
            )
    for number, (node_id, option_id, where) in cited.items():
        if number not in sources:
            checker.node, checker.option = node_id, option_id
            checker.error(
                "situation_not_in_sources",
                f"разбор цитирует карточку {number}, которой нет в source_situations",
                where,
            )
    checker.node = checker.option = None


def iter_ref_lists(scenario):
    """Списки refs всех разборов: вариантов, веток истечения и концовок, с адресом узла."""
    for node_id, option_id, action in iter_actions(scenario):
        debrief = action.get("debrief")
        if isinstance(debrief, dict) and isinstance(debrief.get("refs"), list):
            yield debrief["refs"], node_id, option_id, action
    for node_id, node in scenario["nodes"].items():
        debrief = node.get("debrief") if isinstance(node, dict) else None
        if isinstance(debrief, dict) and isinstance(debrief.get("refs"), list):
            yield debrief["refs"], node_id, None, node


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
    earned = set()
    for node_id, option_id, action in iter_actions(scenario):
        points = action.get("competencies") if isinstance(action.get("competencies"), dict) else {}
        for code, value in points.items():
            used.setdefault(code, (node_id, option_id, action))
            if is_int(value) and value > 0:
                earned.add(code)
    for code, (node_id, option_id, action) in used.items():
        checker.node, checker.option = node_id, option_id
        if code not in known:
            checker.error("unknown_competency", f"компетенции «{code}» нет в competencies.yaml", action)
        elif code not in declared:
            checker.error("competency_not_declared", f"компетенция «{code}» не заявлена в сценарии", action)
    checker.node = checker.option = None
    for code in declared:
        if code not in known:
            continue
        if code not in used:
            checker.error(
                "competency_unused", f"заявленная компетенция «{code}» не встречается в эффектах", scenario
            )
        elif code not in earned:
            # компетенция с одними штрафами никогда не попадает в оценённое: в аналитике она вечный пробел
            checker.error(
                "competency_never_earned",
                f"по компетенции «{code}» нет ни одного варианта с положительными очками",
                scenario,
            )


def check_scale_directions(scenario, checker):
    """Разнонаправленность считается только по вариантам, которые выбирает проводник: ветка
    истечения это не выбор, а разнонаправленность на одно очко это украшение."""
    diverging = loyalty_only = safety_only = False
    minimum = checker.limits["diverging_min"]
    for _, option_id, action in iter_actions(scenario):
        if option_id is None:
            continue
        effects = action.get("effects") if isinstance(action.get("effects"), dict) else {}
        loyalty, safety = effects.get("loyalty", 0), effects.get("safety", 0)
        if not is_int(loyalty) or not is_int(safety):
            continue
        diverging |= loyalty * safety < 0 and min(abs(loyalty), abs(safety)) >= minimum
        loyalty_only |= loyalty != 0 and safety == 0
        safety_only |= safety != 0 and loyalty == 0
    if not diverging:
        checker.error(
            "no_diverging_option",
            f"нет варианта с разнонаправленным влиянием на шкалы не меньше {minimum} по каждой",
            scenario,
        )
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
