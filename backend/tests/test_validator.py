"""Валидатор ловит каждую сломанную фикстуру ожидаемым кодом, минимальный и эталонный сценарии
проходят без ошибок, командная строка печатает итоговую строку и код выхода."""

import copy
import re
import shutil
from pathlib import Path

import pytest

from app.scenarios import validator
from app.scenarios.loader import load_content, read_yaml

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
FIXTURES = Path(__file__).parent / "fixtures"
BROKEN = sorted((FIXTURES / "broken").glob("*.yaml"))
SUMMARY = re.compile(r"^ИТОГ: сценариев=(\d+) узлов=(\d+) ошибок=(\d+) предупреждений=(\d+)$")


@pytest.fixture(scope="module")
def content():
    return load_content(CONTENT_DIR)


@pytest.fixture
def minimal():
    scenario, error = read_yaml(FIXTURES / "valid_minimal.yaml")
    assert error is None
    return scenario


def expected_code(path):
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    return first_line.split(":", 1)[1].strip()


def codes(findings):
    return [item.code for item in findings]


def errors(findings):
    return [item for item in findings if item.severity == "error"]


@pytest.mark.parametrize("path", BROKEN, ids=[path.stem for path in BROKEN])
def test_broken_fixture(path, content):
    scenario, error = read_yaml(path)
    assert error is None
    findings = validator.validate_scenario(scenario, content, path.stem)
    assert expected_code(path) in codes(errors(findings)), [f"{f.code}: {f.message}" for f in findings]


def test_minimal_fixture_is_valid(minimal, content):
    assert validator.validate_scenario(minimal, content, "valid_minimal") == []


def test_reference_scenario_valid(content):
    findings = validator.validate_scenario(
        content.scenarios["medical_chest_pain"], content, "medical_chest_pain"
    )
    assert findings == []


def test_finding_points_to_file_line(content):
    scenario, _ = read_yaml(FIXTURES / "broken" / "missing_next.yaml")
    finding = errors(validator.validate_scenario(scenario, content, "missing_next"))[0]
    assert finding.code == "unknown_node"
    assert finding.node == "intro"
    assert finding.option == "call_chief"
    assert finding.line > 0
    text = validator.format_finding(FIXTURES / "broken" / "missing_next.yaml", finding)
    assert "missing_next.yaml:" in text
    assert "ошибка unknown_node" in text


def option(scenario, node_id, option_id):
    return next(item for item in scenario["nodes"][node_id]["options"] if item["id"] == option_id)


def with_dash(scenario):
    scenario["nodes"]["intro"]["text"] = "Пассажиру плохо " + chr(0x2014) + " он держится за грудь"


def with_stub(scenario):
    scenario["summary"] = "Описание " + "TO" + "DO"


def with_full_name(scenario):
    scenario["context"]["passenger"]["label"] = "Петров А. С. на месте 1А"


def with_duplicate_option(scenario):
    option(scenario, "intro", "talk")["id"] = "wait"


def with_unknown_class(scenario):
    scenario["context"]["service_class"] = "premium"


def with_unavailable_escalation(scenario):
    option(scenario, "intro", "call_chief")["escalation_target"] = "ptb"


def with_role_model(scenario):
    scenario["role_model"] = True


def without_better(scenario):
    del option(scenario, "intro", "give_pills")["debrief"]["better"]


def with_unknown_start(scenario):
    scenario["start"]["node"] = "nowhere"


def with_timer_on_event(scenario):
    scenario["nodes"]["too_late"]["timer"] = copy.deepcopy(scenario["nodes"]["intro"]["timer"])


def with_unknown_field(scenario):
    option(scenario, "intro", "talk")["on_timeout"] = "x"


def with_effect_out_of_range(scenario):
    option(scenario, "intro", "talk")["effects"] = {"loyalty": 80}


def with_unused_competency(scenario):
    scenario["competencies"] = ["medical", "empathy"]


def with_delayed_out_of_range(scenario):
    option(scenario, "intro", "talk")["delayed"] = [
        {"steps": 9, "effects": {"loyalty": -5}, "text": "Поздно."}
    ]


def with_unless_flag_never_set(scenario):
    option(scenario, "intro", "talk")["delayed"] = [
        {"steps": 1, "effects": {"loyalty": -5}, "text": "Поздно.", "unless_flags": {"returned": True}}
    ]


def with_condition_always_shown(scenario):
    option(scenario, "intro", "talk")["when"] = {"loyalty_min": 0}


def with_unknown_option_in_condition(scenario):
    option(scenario, "intro", "talk")["when"] = {"chosen_any": ["nothing"]}


def with_no_ending(scenario):
    scenario["nodes"]["ending_good"]["type"] = "event"
    scenario["nodes"]["ending_good"]["next"] = "ending_bad"
    scenario["nodes"]["ending_bad"]["type"] = "event"
    scenario["nodes"]["ending_bad"]["next"] = "ending_good"


MUTATIONS = [
    (with_dash, "dash_in_text"),
    (with_stub, "stub_in_text"),
    (with_full_name, "full_name_in_text"),
    (with_duplicate_option, "duplicate_option_id"),
    (with_unknown_class, "unknown_class"),
    (with_unavailable_escalation, "escalation_target_unavailable"),
    (with_role_model, "role_chain_impossible"),
    (without_better, "missing_better"),
    (with_unknown_start, "unknown_node"),
    (with_timer_on_event, "timer_on_non_dialog"),
    (with_unknown_field, "schema"),
    (with_effect_out_of_range, "schema"),
    (with_unused_competency, "competency_unused"),
    (with_delayed_out_of_range, "delayed_steps_out_of_range"),
    (with_unless_flag_never_set, "unless_flag_never_set"),
    (with_condition_always_shown, "condition_always_shown"),
    (with_unknown_option_in_condition, "unknown_option_in_condition"),
    (with_no_ending, "cycle"),
]


@pytest.mark.parametrize("mutate, code", MUTATIONS, ids=[code for _, code in MUTATIONS])
def test_mutated_minimal_scenario(minimal, content, mutate, code):
    mutate(minimal)
    findings = validator.validate_scenario(minimal, content, "valid_minimal")
    assert code in codes(errors(findings)), [f"{f.code}: {f.message}" for f in findings]


def test_id_must_match_file_name(minimal, content):
    findings = validator.validate_scenario(minimal, content, "other_name")
    assert any(item.code == "schema" and "имен" in item.message for item in findings)


def test_warnings_do_not_fail_scenario(minimal, content):
    minimal["critical"] = True
    findings = validator.validate_scenario(minimal, content, "valid_minimal")
    assert codes(findings) == ["escalation_expected_missing"]
    assert errors(findings) == []


def test_reference_books_are_checked(content):
    assert validator.check_references(content) == []
    broken = copy.copy(content)
    broken.levels = [{"id": "a", "title": "А", "threshold": 10}]
    broken.rules = copy.deepcopy(content.rules)
    del broken.rules["xp"]["role_bonus"]
    problems = validator.check_references(broken)
    assert any(problem.startswith("levels.yaml") for problem in problems)
    assert "rules.yaml: нет ключа xp.role_bonus" in problems


def test_load_validated_drops_broken_scenario(tmp_path):
    shutil.copytree(CONTENT_DIR, tmp_path / "content")
    shutil.copy(FIXTURES / "broken" / "cycle.yaml", tmp_path / "content" / "scenarios" / "cycle.yaml")
    content, report = validator.load_validated(tmp_path / "content")
    assert "cycle" not in content.scenarios
    assert "medical_chest_pain" in content.scenarios
    assert report["invalid"] == ["cycle"]
    assert report["errors"] == 1


def test_cli_summary_on_reference_content(capsys):
    assert validator.main([str(CONTENT_DIR)]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    match = SUMMARY.match(last)
    assert match, last
    assert int(match.group(1)) >= 1
    assert int(match.group(3)) == 0


def test_cli_reports_errors_with_exit_code(tmp_path, capsys):
    shutil.copytree(CONTENT_DIR, tmp_path / "content")
    target = tmp_path / "content" / "scenarios"
    shutil.copy(FIXTURES / "broken" / "unknown_ref.yaml", target / "unknown_ref.yaml")
    (target / "broken_syntax.yaml").write_text("id: [broken\n", encoding="utf-8")
    assert validator.main([str(tmp_path / "content")]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert any("unknown_ref.yaml" in line and "ошибка unknown_ref" in line for line in lines)
    assert any("broken_syntax.yaml" in line and "yaml_syntax" in line for line in lines)
    match = SUMMARY.match(lines[-1])
    assert match and int(match.group(3)) == 2


def test_cli_markdown_tables(capsys):
    assert validator.main([str(CONTENT_DIR), "--markdown"]) == 0
    out = capsys.readouterr().out
    assert "| Сценарий | Название | Класс |" in out
    assert "| medical_chest_pain | ending_incident_pills |" in out
    assert SUMMARY.match(out.strip().splitlines()[-1])
