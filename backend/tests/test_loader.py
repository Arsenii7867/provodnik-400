"""Загрузчик читает справочники и сценарии, помнит строки YAML и сообщает об ошибках чтения с
файлом и строкой, не роняя остальной контент."""

import shutil
from pathlib import Path

import pytest

from app.scenarios import refs
from app.scenarios.loader import LineDict, load_content, read_yaml

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture
def content_copy(tmp_path):
    shutil.copytree(CONTENT_DIR, tmp_path / "content")
    return tmp_path / "content"


def test_loads_reference_content():
    content = load_content(CONTENT_DIR)
    assert content.errors == []
    assert [item["code"] for item in content.competencies] == [
        "empathy",
        "rules",
        "solution",
        "safety",
        "escalation",
        "medical",
        "inclusion",
    ]
    assert set(content.classes) == {"standard", "comfort", "business", "first"}
    assert content.classes["first"]["loyalty_sensitivity"] == 1.5
    assert [level["threshold"] for level in content.levels] == [0, 150, 400, 800, 1400]
    assert content.rules["outcome"]["incident_if_safety_below"] == 40
    assert content.refs["sit_19"]["kind"] == "situation"
    assert content.refs["sto_011_10_4"]["clause"] == "пункт 10.4"
    assert "medical_chest_pain" in content.scenarios
    assert content.files["medical_chest_pain"].name == "medical_chest_pain.yaml"
    assert content.achievements == []


def test_yaml_dicts_remember_lines():
    content = load_content(CONTENT_DIR)
    scenario = content.scenarios["medical_chest_pain"]
    intro = scenario["nodes"]["intro"]
    assert isinstance(intro, LineDict)
    assert intro.line > scenario.line
    first_option = intro["options"][0]
    assert first_option.line > intro.line
    assert first_option == dict(first_option)


def test_invalid_yaml_reported_with_line(content_copy):
    broken = content_copy / "scenarios" / "broken.yaml"
    broken.write_text("id: broken\ntitle: Сломан\nnodes:\n  intro: [\n", encoding="utf-8")
    content = load_content(content_copy)
    assert "broken" not in content.scenarios
    assert "medical_chest_pain" in content.scenarios
    [error] = content.errors
    assert error["code"] == "yaml_syntax"
    assert error["file"].endswith("broken.yaml")
    assert error["line"] >= 4


def test_duplicate_key_reported(content_copy):
    text = (content_copy / "scenarios" / "medical_chest_pain.yaml").read_text(encoding="utf-8")
    text = text.replace("estimated_minutes: 4\n", "estimated_minutes: 4\nestimated_minutes: 5\n")
    (content_copy / "scenarios" / "medical_chest_pain.yaml").write_text(text, encoding="utf-8")
    content = load_content(content_copy)
    [error] = content.errors
    assert error["code"] == "duplicate_key"
    assert "estimated_minutes" in error["message"]
    assert error["line"] == 12


def test_missing_reference_file_reported(content_copy):
    (content_copy / "levels.yaml").unlink()
    content = load_content(content_copy)
    assert [error["code"] for error in content.errors] == ["missing_file"]
    assert content.levels == []


def test_read_yaml_returns_document_and_no_error():
    doc, error = read_yaml(CONTENT_DIR / "levels.yaml")
    assert error is None
    assert doc[0]["id"] == "trainee"


def test_refs_describe_situation_and_standard():
    content = load_content(CONTENT_DIR)
    situation = refs.describe(content.refs, "sit_19")
    assert situation["clause"] == "карточка 19"
    assert situation["phrase"].startswith("«Я рядом")
    assert situation["quote"].startswith("Вызвать начальника поезда")
    standard = refs.describe(content.refs, "sto_011_10_4")
    assert standard["document"] == "СТО РЖД 03.011-2026"
    assert "неотложный характер" in standard["quote"]
    assert standard["phrase"] == ""
    assert [
        item["key"] for item in refs.describe_many(content.refs, ["sit_19", "missing", "sto_011_10_4"])
    ] == [
        "sit_19",
        "sto_011_10_4",
    ]


def test_refs_check_finds_incomplete_entries():
    problems = refs.check_refs({"sit_5": {"kind": "situation", "number": 7}, "x": {"kind": "law"}})
    assert any("sit_5" in problem and "sit_<номер>" in problem for problem in problems)
    assert any("sit_5" in problem and "нет полей" in problem for problem in problems)
    assert any(problem.startswith("x:") for problem in problems)
