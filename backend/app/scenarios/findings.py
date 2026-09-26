"""Находки валидатора и сборщик находок. Finding это одна ошибка или предупреждение с кодом,
строкой файла и адресом (узел, вариант); Checker подставляет адрес автоматически и держит
пределы из rules.yaml, чтобы проверкам формы не тянуть их каждый раз из content."""

from dataclasses import dataclass


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    line: int = 0
    node: str | None = None
    option: str | None = None


def line_of(obj):
    return getattr(obj, "line", 0)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


class Checker:
    """Собирает находки по одному сценарию; узел и вариант, внутри которых идёт проверка,
    подставляются в каждую находку автоматически."""

    def __init__(self, content, findings):
        self.content = content
        self.findings = findings
        self.limits = content.rules["limits"]
        self.node = None
        self.option = None

    def error(self, code, message, where=None):
        self.findings.append(Finding("error", code, message, line_of(where), self.node, self.option))

    def warning(self, code, message, where=None):
        self.findings.append(Finding("warning", code, message, line_of(where), self.node, self.option))

    def keys(self, obj, allowed, required, label, ignore=()):
        unknown = sorted(str(key) for key in obj if key not in allowed and key not in ignore)
        if unknown:
            self.error("schema", f"{label}: неизвестные поля {', '.join(unknown)}", obj)
        missing = [key for key in required if key not in obj]
        if missing:
            self.error("schema", f"{label}: нет обязательных полей {', '.join(missing)}", obj)

    def integer(self, value, label, where, low=None, high=None):
        if not is_int(value):
            self.error("schema", f"{label} должно быть целым числом", where)
            return False
        if (low is not None and value < low) or (high is not None and value > high):
            self.error("schema", f"{label} вне диапазона {low}..{high}: {value}", where)
            return False
        return True

    def text(self, value, label, where, max_length=None):
        if not is_text(value):
            self.error("schema", f"{label} должно быть непустой строкой", where)
            return False
        if max_length and len(value) > max_length:
            self.error("schema", f"{label} длиннее {max_length} знаков ({len(value)})", where)
        return True

    def boolean(self, value, label, where):
        if not isinstance(value, bool):
            self.error("schema", f"{label} должно быть true или false", where)

    def string_list(self, value, label, where, allow_empty=False):
        if not isinstance(value, list) or any(not is_text(item) for item in value):
            self.error("schema", f"{label} должно быть списком строк", where)
            return False
        if not value and not allow_empty:
            self.error("schema", f"{label} не должно быть пустым", where)
            return False
        return True

    def effects(self, value, where):
        if value is None:
            return
        if not isinstance(value, dict):
            self.error("schema", "effects должно быть словарём с loyalty и safety", where)
            return
        self.keys(value, ("loyalty", "safety"), (), "effects")
        bounds = self.limits["effects"]
        for scale, amount in value.items():
            if scale in ("loyalty", "safety"):
                self.integer(amount, f"effects.{scale}", where, bounds["min"], bounds["max"])

    def competency_points(self, value, where):
        if value is None:
            return
        if not isinstance(value, dict):
            self.error("schema", "competencies должно быть словарём код: очки", where)
            return
        bounds = self.limits["competency_points"]
        for code, amount in value.items():
            self.integer(amount, f"competencies.{code}", where, bounds["min"], bounds["max"])

    def flags(self, value, label, where):
        if value is None:
            return
        if not isinstance(value, dict) or any(not isinstance(item, bool) for item in value.values()):
            self.error("schema", f"{label} должно быть словарём флаг: true или false", where)

    def refs(self, value, where):
        if not isinstance(value, list) or not value:
            self.error("missing_refs", "в разборе нужен хотя бы один ключ из refs.yaml", where)
            return
        for key in value:
            if key not in self.content.refs:
                self.error("unknown_ref", f"ключа «{key}» нет в refs.yaml", where)

    def service_class(self, value, where):
        if value not in self.content.classes:
            self.error("unknown_class", f"класса «{value}» нет в classes.yaml", where)
