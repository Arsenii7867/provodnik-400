"""Справочник ссылок content/refs.yaml: карточки «Ситуаций на борту» (sit_N) и пункты СТО РЖД
(sto_...). Разбор прохождения показывает не ключ, а название и цитату, поэтому здесь одно место,
где ключ превращается в карточку для API, и проверка полноты записей для валидатора."""

KINDS = ("situation", "standard")
REQUIRED = {
    "situation": ("number", "title", "phrase", "rule"),
    "standard": ("document", "clause", "title", "quote"),
}
SITUATIONS_DOCUMENT = "Примеры ситуаций взаимодействия поездного персонала с пассажирами"


def describe(refs: dict, key: str) -> dict:
    """Карточка ссылки для разбора: одна форма и для карточки ситуации, и для нормы."""
    ref = refs[key]
    if ref["kind"] == "situation":
        return {
            "key": key,
            "kind": "situation",
            "title": ref["title"],
            "quote": ref["rule"],
            "phrase": ref["phrase"],
            "document": SITUATIONS_DOCUMENT,
            "clause": f"карточка {ref['number']}",
        }
    return {
        "key": key,
        "kind": "standard",
        "title": ref["title"],
        "quote": ref["quote"],
        "phrase": "",
        "document": ref["document"],
        "clause": ref["clause"],
    }


def describe_many(refs: dict, keys) -> list[dict]:
    return [describe(refs, key) for key in keys if key in refs]


def check_refs(refs) -> list[str]:
    """Сообщения о неполных записях справочника; пустой список означает, что справочник цел."""
    if not isinstance(refs, dict):
        return ["refs.yaml должен быть словарём: ключ ссылки и запись"]
    problems = []
    for key, ref in refs.items():
        if not isinstance(ref, dict) or ref.get("kind") not in KINDS:
            problems.append(f"{key}: kind должен быть situation или standard")
            continue
        missing = [name for name in REQUIRED[ref["kind"]] if not ref.get(name)]
        if missing:
            problems.append(f"{key}: нет полей {', '.join(missing)}")
        if ref["kind"] == "situation" and key != f"sit_{ref.get('number')}":
            problems.append(f"{key}: ключ карточки должен быть sit_<номер>, номер {ref.get('number')}")
        if ref["kind"] == "standard" and not key.startswith("sto_"):
            problems.append(f"{key}: ключ нормы должен начинаться с sto_")
    return problems
