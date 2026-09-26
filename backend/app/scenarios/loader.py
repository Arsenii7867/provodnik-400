"""Чтение контента из папки content: справочники и сценарии в YAML. У каждого словаря из YAML
есть номер строки (LineDict.line), чтобы валидатор печатал «файл:строка». Синтаксические
ошибки и дубли ключей не роняют загрузку, а попадают в Content.errors."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.scenarios import refs as refs_book
from app.scenarios import rules as rulebook
from app.services import achievements as achievements_book

REFERENCE_FILES = ("competencies", "classes", "levels", "rules", "refs", "achievements", "challenges")
# эти справочники появляются позже остальных; без них контент считается целым
OPTIONAL_REFERENCES = ("achievements", "challenges")
CLASS_FIELDS = ("title", "layout", "wait_minutes", "loyalty_sensitivity")


class LineDict(dict):
    """Обычный словарь плюс номер строки, с которой он начинается в файле."""

    line = 0


class DuplicateKey(yaml.constructor.ConstructorError):
    """Повтор ключа в словаре YAML: стандартный загрузчик молча берёт последнее значение."""


class LineLoader(yaml.SafeLoader):
    """SafeLoader, у которого словари это LineDict с номером строки (см. construct_line_mapping)."""


def construct_line_mapping(loader, node):
    loader.flatten_mapping(node)
    mapping = LineDict()
    mapping.line = node.start_mark.line + 1
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise DuplicateKey(None, None, f"ключ «{key}» повторяется", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_line_mapping)


@dataclass
class Content:
    scenarios: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    competencies: list = field(default_factory=list)
    classes: dict = field(default_factory=dict)
    levels: list = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    refs: dict = field(default_factory=dict)
    achievements: list = field(default_factory=list)
    challenges: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def read_yaml(path):
    """Возвращает пару (документ, ошибка); ошибка это словарь file, line, code, message или None."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.load(handle, Loader=LineLoader), None
    except DuplicateKey as exc:
        line = exc.problem_mark.line + 1
        return None, {"file": str(path), "line": line, "code": "duplicate_key", "message": exc.problem}
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark else 0
        message = exc.problem or "не удалось разобрать YAML"
        return None, {"file": str(path), "line": line, "code": "yaml_syntax", "message": message}
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
        # файл в другой кодировке, с управляющим символом или занят редактором: это ошибка файла, а не сервера
        message = str(exc).splitlines()[0][:200] if str(exc) else exc.__class__.__name__
        return None, {"file": str(path), "line": 0, "code": "unreadable_file", "message": message}


def load_content(content_dir):
    """Читает справочники и все scenarios/*.yaml. Сценарии здесь ещё не проверены: валидацию и
    отсев сломанных делает validator.load_validated."""
    content_dir = Path(content_dir)
    content = Content()
    for name in REFERENCE_FILES:
        path = content_dir / f"{name}.yaml"
        if not path.exists():
            if name not in OPTIONAL_REFERENCES:
                content.errors.append(
                    {"file": str(path), "line": 0, "code": "missing_file", "message": "справочник не найден"}
                )
            continue
        doc, error = read_yaml(path)
        if error:
            content.errors.append(error)
        elif doc is not None:
            setattr(content, name, doc)
    for path in sorted((content_dir / "scenarios").glob("*.yaml")):
        add_scenario(content, path)
    return content


def check_references(content):
    """Полнота справочников; каждое сообщение начинается с имени файла."""
    problems = []
    codes = [item.get("code") for item in content.competencies if isinstance(item, dict)]
    titled = all(isinstance(item, dict) and item.get("title") for item in content.competencies)
    if not codes or len(codes) != len(set(codes)) or not titled:
        problems.append("competencies.yaml: список компетенций с уникальными code и title")
    if not isinstance(content.classes, dict) or not content.classes:
        problems.append("classes.yaml: словарь классов не должен быть пустым")
    for code, item in content.classes.items() if isinstance(content.classes, dict) else ():
        if not isinstance(item, dict) or any(item.get(name) is None for name in CLASS_FIELDS):
            problems.append(f"classes.yaml: у класса {code} нужны поля {', '.join(CLASS_FIELDS)}")
        elif not isinstance(item["loyalty_sensitivity"], int | float) or item["loyalty_sensitivity"] <= 0:
            problems.append(f"classes.yaml: loyalty_sensitivity класса {code} должна быть больше нуля")
    thresholds = [item.get("threshold") for item in content.levels if isinstance(item, dict)]
    if not thresholds or thresholds[0] != 0 or thresholds != sorted(set(thresholds)):
        problems.append("levels.yaml: пороги начинаются с 0 и строго растут")
    problems += [f"rules.yaml: нет ключа {path}" for path in rulebook.missing_keys(content.rules)]
    problems += [f"refs.yaml: {problem}" for problem in refs_book.check_refs(content.refs)]
    # реестр типов правил живёт рядом с выдачей достижений: неизвестный тип ловится при чтении файла
    problems += [f"achievements.yaml: {item}" for item in achievements_book.check_achievements(content)]
    return problems


def add_scenario(content, path):
    doc, error = read_yaml(path)
    if error:
        content.errors.append(error)
        return
    scenario_id = doc.get("id") if isinstance(doc, dict) else None
    key = scenario_id if isinstance(scenario_id, str) else path.stem
    if key in content.scenarios:
        message = f"сценарий с id «{key}» уже прочитан из {content.files[key].name}"
        content.errors.append(
            {"file": str(path), "line": 1, "code": "duplicate_scenario_id", "message": message}
        )
        return
    content.scenarios[key] = doc
    content.files[key] = path
