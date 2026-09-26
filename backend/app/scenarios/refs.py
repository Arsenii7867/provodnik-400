"""Справочник ссылок content/refs.yaml: карточки «Ситуаций на борту» (sit_N), пункты СТО РЖД
(sto_...) и ролевая модель со слайда организаторов (model_...). Разбор прохождения показывает
не ключ, а название и цитату, поэтому здесь одно место, где ключ превращается в карточку для
API, и проверка полноты записей для валидатора."""

KINDS = ("situation", "standard", "model")
REQUIRED = {
    "situation": ("number", "title", "phrase", "rule"),
    "standard": ("document", "clause", "title", "quote"),
    "model": ("document", "clause", "title", "quote"),
}
PREFIXES = {"standard": "sto_", "model": "model_"}
SITUATIONS_DOCUMENT = "Примеры ситуаций взаимодействия поездного персонала с пассажирами"


def describe(refs, key):
    """Карточка ссылки для разбора: одна форма и для карточки ситуации, и для нормы, и для
    ролевой модели. У карточки цитата это реакция, а совет карточки идёт отдельной фразой,
    чтобы дословную реакцию нельзя было спутать с пересказом."""
    ref = refs[key]
    if ref["kind"] == "situation":
        quote = ref["rule"]
        if ref.get("tip"):
            quote = f"{quote} Совет карточки: {ref['tip']}"
        return {
            "key": key,
            "kind": "situation",
            "title": ref["title"],
            "quote": quote,
            "phrase": ref["phrase"],
            "document": SITUATIONS_DOCUMENT,
            "clause": f"карточка {ref['number']}",
            "number": ref["number"],
            "reconstructed": False,
        }
    return {
        "key": key,
        "kind": ref["kind"],
        "title": ref["title"],
        "quote": ref["quote"],
        "phrase": "",
        "document": ref["document"],
        "clause": str(ref["clause"]),
        "number": None,
        # нумерация пунктов восстановлена по оглавлению: разбор показывает номер вместе с цитатой
        "reconstructed": bool(ref.get("reconstructed")),
    }


def describe_many(refs, keys):
    return [describe(refs, key) for key in keys if key in refs]


def check_refs(refs):
    """Сообщения о неполных записях справочника; пустой список означает, что справочник цел."""
    if not isinstance(refs, dict):
        return ["refs.yaml должен быть словарём: ключ ссылки и запись"]
    problems = []
    for key, ref in refs.items():
        if not isinstance(ref, dict) or ref.get("kind") not in KINDS:
            problems.append(f"{key}: kind должен быть одним из {', '.join(KINDS)}")
            continue
        missing = [name for name in REQUIRED[ref["kind"]] if not ref.get(name)]
        if missing:
            problems.append(f"{key}: нет полей {', '.join(missing)}")
        if ref["kind"] == "situation" and key != f"sit_{ref.get('number')}":
            problems.append(f"{key}: ключ карточки должен быть sit_<номер>, номер {ref.get('number')}")
        if ref["kind"] == "situation" and "tip" in ref and not isinstance(ref["tip"], str):
            problems.append(f"{key}: tip должен быть строкой с советом карточки")
        prefix = PREFIXES.get(ref["kind"])
        if prefix and not key.startswith(prefix):
            problems.append(f"{key}: ключ записи kind {ref['kind']} должен начинаться с {prefix}")
    return problems
