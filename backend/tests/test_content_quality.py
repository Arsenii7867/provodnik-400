"""Содержательность каждого сценария в content/scenarios: проверки декоративности через движок
и перебор путей, разбор со ссылками, чистые тексты, заявленные компетенции и форма сценария по
постановке. Падение здесь чинится в сценарии, а не в тесте."""

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.scenarios import analysis, engine, validator
from app.scenarios.loader import load_content

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SCENARIO_FILES = sorted((CONTENT_DIR / "scenarios").glob("*.yaml"))
T0 = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
NODES_MIN = 8
ENDINGS_MIN = 3


@pytest.fixture(scope="module")
def content():
    return load_content(CONTENT_DIR)


@pytest.fixture(scope="module", params=SCENARIO_FILES, ids=[path.stem for path in SCENARIO_FILES])
def scenario(request, content):
    return content.scenarios[request.param.stem]


@pytest.fixture(scope="module")
def analyzed(scenario, content):
    return analysis.analyze(scenario, content)


def actions(scenario):
    """Варианты и ветки истечения: всё, у чего есть эффекты, очки и разбор."""
    for node in scenario["nodes"].values():
        yield from node.get("options") or []
        if node.get("timer"):
            yield node["timer"]["on_expire"]


def effects_of(action):
    effects = action.get("effects") or {}
    return effects.get("loyalty", 0), effects.get("safety", 0)


def moves(scenario, state):
    node = scenario["nodes"][state["node"]]
    if node["type"] == "event":
        return [engine.CONTINUE]
    ids = [option["id"] for option in engine.available_options(scenario, state)]
    return ids + (["expire"] if node.get("timer") else [])


def make_move(scenario, content, state, move):
    if move == "expire":
        return engine.apply_expire_branch(scenario, content, state)
    return engine.apply_option(scenario, content, state, move)


def best_prefix_to(scenario, content, target):
    """Ходы до узла target по родному классу с лучшим состоянием на входе: без истечений и с
    наибольшей суммой шкал, чтобы сравнивать истечение с честной игрой, а не с провалом."""
    found = []
    stack = [(engine.start_state(scenario, content), [])]
    while stack:
        state, prefix = stack.pop()
        if state["node"] == target:
            found.append((-state["expired_timers"], state["loyalty"] + state["safety"], prefix))
            continue
        if state["status"] == "finished":
            continue
        for move in moves(scenario, state):
            branch = copy.deepcopy(state)
            make_move(scenario, content, branch, move)
            stack.append((branch, prefix + [move]))
    assert found, f"узел {target} недостижим"
    return max(found)[2]


def finals_from(scenario, content, state):
    if state["status"] == "finished":
        return {(state["outcome"], state["loyalty"], state["safety"])}
    finals = set()
    for move in moves(scenario, state):
        branch = copy.deepcopy(state)
        make_move(scenario, content, branch, move)
        finals |= finals_from(scenario, content, branch)
    return finals


def replay(scenario, content, prefix):
    """Проходит prefix со временем: между ходами секунда, истечение ровно по дедлайну."""
    now = T0
    state = engine.start(scenario, content, now)
    for move in prefix:
        if move == "expire":
            now = state["deadline_at"]
            state, _ = engine.apply_expiry(scenario, content, state, now)
        else:
            now += timedelta(seconds=1)
            state, _ = engine.apply_choice(scenario, content, state, move, now)
    return state, now


def test_has_diverging_and_single_scale_options(scenario):
    pairs = [effects_of(action) for action in actions(scenario)]
    assert any(loyalty * safety < 0 for loyalty, safety in pairs), "нет разнонаправленного варианта"
    assert any(loyalty != 0 and safety == 0 for loyalty, safety in pairs), "нет варианта только по лояльности"
    assert any(safety != 0 and loyalty == 0 for loyalty, safety in pairs), (
        "нет варианта только по безопасности"
    )


def test_outcomes_and_spread(analyzed, content):
    own = analyzed["own"]
    settings = content.rules["analysis"]
    assert not analyzed["truncated"]
    assert len(own["outcomes"]) >= settings["min_outcomes"], own["outcomes"]
    for scale in ("loyalty", "safety"):
        assert own[scale]["max"] - own[scale]["min"] >= settings["min_scale_spread"], scale


def test_three_endings_min(scenario, analyzed):
    endings = {node_id for node_id, node in scenario["nodes"].items() if node["type"] == "ending"}
    assert len(endings) >= ENDINGS_MIN
    reached = set()
    for summary in analyzed["by_class"].values():
        reached |= set(summary["endings"])
    assert reached == endings
    # профили сравниваются по родному классу сценария: в нём его и проходят
    own = analyzed["own"]["endings"]
    profiles = {
        (item["loyalty"]["min"], item["loyalty"]["max"], item["safety"]["min"], item["safety"]["max"])
        for item in own.values()
    }
    assert len(profiles) == len(own), "у двух концовок одинаковый профиль шкал"


def test_timer_branch_changes_state(scenario, content):
    timers = [node_id for node_id, node in scenario["nodes"].items() if node.get("timer")]
    assert timers, "в сценарии нет таймера"
    for node_id in timers:
        node = scenario["nodes"][node_id]
        target = node["timer"]["on_expire"]["next"]
        assert target in scenario["nodes"]
        assert all(option["next"] != target for option in node["options"])
        state = engine.start_state(scenario, content)
        for move in best_prefix_to(scenario, content, node_id):
            make_move(scenario, content, state, move)
        expired = copy.deepcopy(state)
        engine.apply_expire_branch(scenario, content, expired)
        assert expired["node"] == target
        assert expired["expired_timers"] == state["expired_timers"] + 1
        answered = set()
        for option in engine.available_options(scenario, state):
            branch = copy.deepcopy(state)
            engine.apply_option(scenario, content, branch, option["id"])
            assert branch["node"] != expired["node"]
            answered |= finals_from(scenario, content, branch)
        after_expiry = finals_from(scenario, content, expired)
        best_expired = analysis.final_key(analysis.best_final(after_expiry))
        best_answered = analysis.final_key(analysis.best_final(answered))
        assert best_expired < best_answered, f"истечение в {node_id} не ухудшает лучший финал"


def test_conditions_shown_and_hidden(scenario, analyzed):
    conditional = [
        (node_id, option["id"])
        for node_id, node in scenario["nodes"].items()
        for option in node.get("options") or []
        if option.get("when")
    ]
    for key in conditional:
        assert key in analyzed["shown"], key
        assert key in analyzed["hidden"], key
    assert analyzed["empty_nodes"] == set()


def test_has_condition_or_delayed(scenario):
    options = [option for node in scenario["nodes"].values() for option in node.get("options") or []]
    assert any(option.get("when") or option.get("delayed") for option in options)


def test_choice_after_deadline_changes_node(scenario, content):
    for node_id, node in scenario["nodes"].items():
        if not node.get("timer"):
            continue
        state, now = replay(scenario, content, best_prefix_to(scenario, content, node_id))
        assert state["node"] == node_id and state["deadline_at"] is not None
        options = engine.available_options(scenario, state)
        option = next((item for item in options if item["debrief"]["verdict"] == "best"), options[0])
        on_time, on_time_step = engine.apply_choice(
            scenario, content, copy.deepcopy(state), option["id"], now + timedelta(seconds=1)
        )
        late_moment = state["deadline_at"] + timedelta(seconds=2)
        late, late_step = engine.apply_choice(
            scenario, content, copy.deepcopy(state), option["id"], late_moment, 1.0
        )
        assert late_step["expired"] and not on_time_step["expired"]
        assert late["node"] == node["timer"]["on_expire"]["next"] != on_time["node"]
        assert (late["loyalty"], late["safety"]) != (on_time["loyalty"], on_time["safety"]), node_id
        assert late_step["effects"] == (node["timer"]["on_expire"].get("effects") or {})


def check_debrief(debrief, content, need_better):
    assert debrief["why"].strip()
    if need_better:
        assert debrief["better"].strip()
    assert debrief["refs"]
    assert all(key in content.refs for key in debrief["refs"]), debrief["refs"]


def test_refs_and_debrief_complete(scenario, content):
    for node in scenario["nodes"].values():
        if node["type"] == "ending":
            assert node["debrief"]["summary"].strip()
            assert node["debrief"]["refs"] and all(key in content.refs for key in node["debrief"]["refs"])
        for option in node.get("options") or []:
            check_debrief(option["debrief"], content, need_better=option["debrief"]["verdict"] != "best")
        if node.get("timer"):
            check_debrief(node["timer"]["on_expire"]["debrief"], content, need_better=True)


def test_texts_clean(scenario):
    for text, node_id, option_id, _ in validator.iter_texts(scenario):
        where = f"{node_id}/{option_id}: {text[:40]}"
        assert not any(dash in text for dash in validator.DASHES), where
        assert not validator.FULL_NAME.search(text), where
        assert not validator.STUB_PATTERN.search(text), where


def test_declared_competencies_used(scenario, content):
    known = {item["code"] for item in content.competencies}
    declared = set(scenario["competencies"])
    used = {code for action in actions(scenario) for code in action.get("competencies") or {}}
    assert declared <= known
    assert used == declared


def test_scenario_shape(scenario, analyzed):
    assert len(scenario["nodes"]) >= NODES_MIN
    if scenario["role_model"]:
        assert analyzed["role_chain_possible"]
    assert scenario["context"]["passenger"]["label"].strip()


def test_validator_finds_no_errors(scenario, content):
    findings = validator.validate_scenario(scenario, content, scenario["id"])
    assert [item for item in findings if item.severity == "error"] == []
