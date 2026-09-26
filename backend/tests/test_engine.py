"""Движок прохождения на эталоне и на тестовом сценарии с условиями по классу: истечение и
поздний выбор, условия по флагам, шкалам, классу и прошлым выборам, отложенные последствия,
цепочка ролевой модели, исходы, ошибки с кодами, детерминизм и изоляция от БД и веба."""

import ast
import copy
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.scenarios import engine, rules, validator
from app.scenarios.loader import load_content, read_yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONTENT_DIR = BACKEND_DIR.parent / "content"
FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
GRACE = 1.0
BEST_PATH = ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"]
BEST_TABLET_PATH = ["acknowledge_ask", "bring_tablet", "move_to_rack", "thank_assure"]
PURE_MODULES = ["app/scenarios/engine.py", "app/scenarios/rules.py", "app/scenarios/analysis.py"]
FORBIDDEN_IMPORTS = ("sqlalchemy", "fastapi", "starlette", "pydantic", "app.db", "app.models", "app.main")


@pytest.fixture(scope="module")
def content():
    return load_content(CONTENT_DIR)


@pytest.fixture(scope="module")
def medical(content):
    return content.scenarios["medical_chest_pain"]


@pytest.fixture(scope="module")
def tablet(content):
    scenario, error = read_yaml(FIXTURES / "class_options.yaml")
    assert error is None
    assert validator.validate_scenario(scenario, content, "class_options") == []
    return scenario


def play(scenario, content, moves, service_class=None, seconds=5):
    """Проходит сценарий по списку ходов, между ходами seconds секунд; ход «expire» ждёт дедлайн."""
    now = T0
    state = engine.start(scenario, content, now, service_class)
    step = None
    for move in moves:
        if move == "expire":
            now = state["deadline_at"] + timedelta(seconds=GRACE)
            state, step = engine.apply_expiry(scenario, content, state, now, GRACE)
        else:
            now += timedelta(seconds=seconds)
            state, step = engine.apply_choice(scenario, content, state, move, now, GRACE)
    return state, step


def option_ids(scenario, state):
    return [option["id"] for option in engine.available_options(scenario, state)]


def option(scenario, node_id, option_id):
    return next(item for item in scenario["nodes"][node_id]["options"] if item["id"] == option_id)


def test_timeout_changes_outcome(medical, content):
    answered, _ = play(medical, content, BEST_PATH)
    after_expiry = ["expire", "check_and_radio_chief", "ask_history_only", "pa_medic", "brief_medic_full"]
    expired, _ = play(medical, content, after_expiry + ["announce_calm"])
    assert answered["outcome"] == "exemplary"
    assert expired["outcome"] == "acceptable"
    assert (answered["expired_timers"], expired["expired_timers"]) == (0, 1)
    first = expired["steps"][0]
    assert first["expired"] is True and first["option_id"] is None
    assert first["node_id"] == "intro" and first["next_node"] == "collapsed"
    assert all(option["next"] != "collapsed" for option in medical["nodes"]["intro"]["options"])
    assert (expired["loyalty"], expired["safety"]) == (59, 90)
    assert (answered["loyalty"], answered["safety"]) == (98, 100)


def test_expired_timer_blocks_exemplary(tablet, content):
    """Правило no_expired_timers решает исход само по себе: путь с истечением, который по шкалам
    проходит пороги, остаётся приемлемым, а с выключенным правилом в копии rules.yaml становится
    образцовым."""
    gentle = copy.deepcopy(tablet)
    gentle["nodes"]["intro"]["timer"]["on_expire"]["effects"] = {"loyalty": -2}
    path = ["expire", "continue", "bring_tablet", "move_to_rack", "thank_assure"]
    state, _ = play(gentle, content, path, "business")
    thresholds = content.rules["outcome"]["exemplary_if"]
    assert state["loyalty"] >= thresholds["loyalty_min"] and state["safety"] >= thresholds["safety_min"]
    assert state["expired_timers"] == 1 and state["outcome"] == "acceptable"
    lenient = copy.deepcopy(content)
    lenient.rules["outcome"]["exemplary_if"]["no_expired_timers"] = False
    relaxed, _ = play(gentle, lenient, path, "business")
    assert relaxed["outcome"] == "exemplary"


def test_exemplary_needs_both_thresholds(tablet, content):
    high_loyalty = copy.deepcopy(tablet)
    option(high_loyalty, "luggage", "move_to_rack")["effects"] = {"safety": 5}
    state, _ = play(high_loyalty, content, BEST_TABLET_PATH, "business")
    assert state["loyalty"] >= 70 and state["safety"] < 75 and state["outcome"] == "acceptable"
    high_safety = copy.deepcopy(tablet)
    option(high_safety, "farewell", "thank_assure")["effects"] = {"loyalty": -20}
    state, _ = play(high_safety, content, BEST_TABLET_PATH, "business")
    assert state["safety"] >= 75 and state["loyalty"] < 70 and state["outcome"] == "acceptable"


def test_negative_points_do_not_reduce_earned(tablet, content):
    state, _ = play(tablet, content, ["acknowledge_ask", "give_own_phone"])
    assert state["earned"] == {"empathy": 2}
    assert state["assessed"]["rules"] == 2 and "safety" not in state["assessed"]


def test_hidden_options_are_not_assessed(tablet, medical, content):
    """Вариант, скрытый классом или прошлым верным решением, не упущен: в стандарт-классе планшет
    не считается оценённым, а в эталоне лучший путь даёт полное владение по всем компетенциям."""
    standard, _ = play(tablet, content, ["acknowledge_ask", "explain_class"])
    business, _ = play(tablet, content, ["acknowledge_ask", "explain_class"], "business")
    assert "solution" not in standard["assessed"]
    assert business["assessed"]["solution"] == 2
    best, _ = play(medical, content, BEST_PATH)
    for code in medical["competencies"]:
        assert best["earned"][code] == best["assessed"][code] > 0, code


def test_every_when_key_is_enforced(tablet, content):
    """Каждый ключ условия показа читается движком: not_chosen, loyalty_max и safety_min тоже."""
    gated = copy.deepcopy(tablet)
    option(gated, "request", "give_own_phone")["when"] = {"not_chosen": ["acknowledge_ask"]}
    polite, _ = play(gated, content, ["acknowledge_ask"])
    rude, _ = play(gated, content, ["refuse_flat"])
    assert "give_own_phone" not in option_ids(gated, polite)
    assert "give_own_phone" in option_ids(gated, rude)
    capped = copy.deepcopy(tablet)
    option(capped, "request", "give_own_phone")["when"] = {"loyalty_max": 40}
    polite, _ = play(capped, content, ["acknowledge_ask"])
    rude, _ = play(capped, content, ["refuse_flat"])
    assert "give_own_phone" not in option_ids(capped, polite)
    assert "give_own_phone" in option_ids(capped, rude)
    guarded = copy.deepcopy(tablet)
    option(guarded, "luggage", "leave_in_aisle")["when"] = {"safety_min": 60}
    safe, _ = play(guarded, content, ["acknowledge_ask", "explain_class", "offer_wifi"])
    risky, _ = play(guarded, content, ["acknowledge_ask", "give_own_phone"])
    assert "leave_in_aisle" in option_ids(guarded, safe)
    assert "leave_in_aisle" not in option_ids(guarded, risky)


def test_forced_acceptable_and_start_flags(tablet, content):
    capped = copy.deepcopy(tablet)
    capped["nodes"]["ending_calm"]["forced_outcome"] = "acceptable"
    state, _ = play(capped, content, BEST_TABLET_PATH, "business")
    assert state["loyalty"] >= 70 and state["safety"] >= 75 and state["outcome"] == "acceptable"
    flagged = copy.deepcopy(tablet)
    flagged["start"]["flags"] = {"returned": True}
    option(flagged, "request", "give_own_phone")["when"] = {"flags_all": {"returned": True}}
    state, _ = play(flagged, content, ["acknowledge_ask"])
    assert state["flags"] == {"returned": True}
    assert "give_own_phone" in option_ids(flagged, state)


def test_fractional_sensitivity_rounds_half_up(tablet, content):
    """Чувствительность 1.15 даёт 1.15 x 50 = 57.49999 в двоичной дроби: округление обязано дать
    58, как посчитает жюри на бумаге."""
    tuned = copy.deepcopy(content)
    tuned.classes["standard"]["loyalty_sensitivity"] = 1.15
    generous = copy.deepcopy(tablet)
    generous["start"]["loyalty"] = 40
    option(generous, "intro", "acknowledge_ask")["effects"] = {"loyalty": 50}
    state, _ = play(generous, tuned, ["acknowledge_ask"])
    assert state["loyalty"] == 40 + 58


def test_scales_diverge_on_choice(medical, content):
    state, step = play(medical, content, ["give_own_pills"])
    assert step["loyalty_after"] > step["loyalty_before"]
    assert step["safety_after"] < step["safety_before"]
    # бизнес-класс: плюс 5 лояльности превращаются в плюс 6 (5 x 1.25 с округлением от нуля)
    assert (state["loyalty"], state["safety"]) == (66, 40)


def test_flag_gates_choice_later(medical, content):
    with_chief, _ = play(medical, content, ["call_chief_stay", "water_and_calm"])
    without, _ = play(medical, content, ["finish_trolley_first", "ask_history_only"])
    assert with_chief["node"] == without["node"] == "help_options"
    assert "pa_medic" in option_ids(medical, with_chief)
    assert "radio_chief_late" not in option_ids(medical, with_chief)
    assert "pa_medic" not in option_ids(medical, without)
    assert "radio_chief_late" in option_ids(medical, without)
    with pytest.raises(engine.EngineError) as caught:
        engine.apply_choice(medical, content, without, "pa_medic", T0 + timedelta(seconds=15), GRACE)
    assert caught.value.code == "option_unavailable"
    assert without["step_no"] == 2 and without["node"] == "help_options"


def test_choice_after_deadline_rejected(medical, content):
    state = engine.start(medical, content, T0)
    assert state["deadline_at"] == T0 + timedelta(seconds=20)
    state, step = engine.apply_choice(
        medical, content, state, "call_chief_stay", T0 + timedelta(seconds=22), GRACE
    )
    assert step["expired"] is True and step["option_id"] is None
    assert state["node"] == "collapsed"
    assert (state["loyalty"], state["safety"]) == (47, 50)
    assert state["chosen"] == [] and state["flags"] == {}
    assert step["answered_in_seconds"] == 22.0
    assert state["deadline_at"] is None
    within_grace = engine.start(medical, content, T0)
    within_grace, step = engine.apply_choice(
        medical, content, within_grace, "call_chief_stay", T0 + timedelta(seconds=20.5), GRACE
    )
    assert step["expired"] is False and within_grace["node"] == "at_the_seat"


def test_late_choice_still_needs_valid_option(medical, content):
    """Мусорный или скрытый id после дедлайна это отказ, а не тихое истечение: клиент не может
    закрыть таймер чем попало."""
    state = engine.start(medical, content, T0)
    with pytest.raises(engine.EngineError) as caught:
        engine.apply_choice(medical, content, state, "nonexistent", T0 + timedelta(seconds=30), GRACE)
    assert caught.value.code == "option_unavailable"
    assert state["node"] == "intro" and state["expired_timers"] == 0


def test_unknown_class_rejected(medical, content):
    with pytest.raises(engine.EngineError) as caught:
        engine.start(medical, content, T0, "premium")
    assert caught.value.code == "unknown_class"


def test_expiry_points_count_in_assessed(tablet, content):
    """Положительные очки в ветке истечения входят в оценённое: заработанное не превышает его."""
    plain, _ = play(tablet, content, ["expire"])
    assert "rules" not in plain["assessed"]
    generous = copy.deepcopy(tablet)
    generous["nodes"]["intro"]["timer"]["on_expire"]["competencies"] = {"rules": 1}
    state, _ = play(generous, content, ["expire"])
    assert state["earned"]["rules"] == state["assessed"]["rules"] == 1


def test_expiry_before_deadline_is_too_early(medical, content):
    state = engine.start(medical, content, T0)
    with pytest.raises(engine.EngineError) as caught:
        engine.apply_expiry(medical, content, state, T0 + timedelta(seconds=5), GRACE)
    assert caught.value.code == "too_early"
    assert state["node"] == "intro" and state["step_no"] == 0
    state, step = engine.apply_expiry(medical, content, state, T0 + timedelta(seconds=19), GRACE)
    assert step["expired"] and state["node"] == "collapsed"


def test_expiry_without_timer_and_after_finish(medical, content):
    state, _ = play(medical, content, ["call_chief_stay"])
    assert state["deadline_at"] is None
    with pytest.raises(engine.EngineError) as caught:
        engine.apply_expiry(medical, content, state, T0 + timedelta(seconds=60), GRACE)
    assert caught.value.code == "no_timer"
    finished, _ = play(medical, content, BEST_PATH)
    assert finished["status"] == "finished"
    for action in (
        lambda: engine.apply_choice(medical, content, finished, "announce_calm", T0, GRACE),
        lambda: engine.apply_expiry(medical, content, finished, T0, GRACE),
    ):
        with pytest.raises(engine.EngineError) as caught:
            action()
        assert caught.value.code == "run_not_active"


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def test_engine_has_no_db_or_web_imports():
    for relative in PURE_MODULES:
        for name in imported_modules(BACKEND_DIR / relative):
            assert not name.startswith(FORBIDDEN_IMPORTS), f"{relative} импортирует {name}"
    probe = (
        "import sys, app.scenarios.engine, app.scenarios.analysis; "
        "print(','.join(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('sqlalchemy', 'fastapi', 'starlette', 'pydantic'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=BACKEND_DIR, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_class_changes_options_and_effects(tablet, content):
    standard, _ = play(tablet, content, ["acknowledge_ask"])
    business, _ = play(tablet, content, ["acknowledge_ask"], "business")
    first, _ = play(tablet, content, ["acknowledge_ask"], "first")
    assert (standard["loyalty"], business["loyalty"], first["loyalty"]) == (60, 63, 65)
    assert "bring_tablet" not in option_ids(tablet, standard)
    assert "bring_tablet" in option_ids(tablet, business)
    assert "bring_tablet" in option_ids(tablet, first)
    with pytest.raises(engine.EngineError) as caught:
        engine.apply_choice(tablet, content, standard, "bring_tablet", T0 + timedelta(seconds=10), GRACE)
    assert caught.value.code == "option_unavailable"
    # безопасность классом не масштабируется
    standard, _ = play(tablet, content, ["acknowledge_ask", "give_own_phone"])
    first, _ = play(tablet, content, ["acknowledge_ask", "give_own_phone"], "first")
    assert standard["safety"] == first["safety"] == 40


def test_timer_seconds_by_class(tablet, medical, content):
    assert engine.start(tablet, content, T0)["deadline_at"] == T0 + timedelta(seconds=40)
    assert engine.start(tablet, content, T0, "first")["deadline_at"] == T0 + timedelta(seconds=15)
    assert engine.timer_seconds(medical["nodes"]["intro"], "first") == 20
    assert engine.timer_seconds(medical["nodes"]["at_the_seat"], "first") is None
    late = engine.start(tablet, content, T0, "first")
    late, step = engine.apply_choice(
        tablet, content, late, "acknowledge_ask", T0 + timedelta(seconds=17), GRACE
    )
    assert step["expired"] and late["node"] == "ignored" and step["timer_seconds"] == 15


def test_role_chain_bonus(medical, tablet, content):
    """Бонус за цепочку начисляется только за полную последовательность в порядке; само число
    берётся из rules.yaml, и его проверяет test_scoring."""
    state, _ = play(medical, content, BEST_PATH)
    assert state["role_chain"] == ["acknowledge", "rule", "solution", "assure"]
    assert engine.role_chain_progress(state) == {
        "steps": ["acknowledge", "rule", "solution", "assure"],
        "next_expected": None,
        "complete": True,
    }
    partial, _ = play(medical, content, ["call_chief_stay", "ask_history_only", "pa_medic"])
    assert partial["role_chain"] == ["acknowledge", "solution"]
    assert engine.role_chain_progress(partial) == {
        "steps": ["acknowledge"],
        "next_expected": "rule",
        "complete": False,
    }
    # шаг цепочки с вердиктом bad не засчитывается
    bad_solution, _ = play(tablet, content, ["acknowledge_ask", "explain_class", "offer_nothing"])
    assert bad_solution["role_chain"] == ["acknowledge", "rule"]


def test_role_chain_requires_order():
    assert engine.role_chain_complete(["acknowledge", "solution", "rule", "solution", "assure"])
    assert not engine.role_chain_complete(["rule", "acknowledge", "solution", "assure"])
    assert not engine.role_chain_complete([])


def test_delayed_effect_applies_after_steps(tablet, content):
    state, step = play(tablet, content, ["promise_check", "explain_class", "offer_wifi"])
    assert state["steps"][1]["delayed_applied"] == []
    [applied] = step["delayed_applied"]
    assert applied["option_id"] == "promise_check" and applied["cancelled"] is False
    assert applied["effects"] == {"loyalty": -15}
    assert state["loyalty"] == 50 + 5 - 5 - 15 + 10
    assert state["delayed"] == []


def test_delayed_effect_cancelled_by_flag(tablet, content):
    state, step = play(tablet, content, ["promise_check", "return_with_answer", "move_to_rack"])
    assert state["flags"] == {"returned": True}
    [applied] = step["delayed_applied"]
    assert applied["cancelled"] is True
    assert step["loyalty_before"] == step["loyalty_after"] == 65
    assert state["delayed"] == []


def test_delayed_applies_at_ending(medical, content):
    path = ["call_chief_stay", "water_and_calm", "pa_medic", "let_medic_handle_and_go", "announce_calm"]
    state, step = play(medical, content, path)
    assert state["status"] == "finished" and state["delayed"] == []
    [applied] = step["delayed_applied"]
    assert applied["option_id"] == "let_medic_handle_and_go" and applied["cancelled"] is False
    # заверение дало плюс 6, невыполненное обещание отняло 13 (10 x 1.25 с округлением от нуля)
    assert state["loyalty"] == step["loyalty_before"] + 6 - 13


def test_condition_by_scales_and_chosen(medical, tablet, content):
    low, _ = play(medical, content, ["give_own_pills", "continue", "ask_history_only"])
    high, _ = play(medical, content, ["call_chief_stay", "water_and_calm"])
    assert low["node"] == high["node"] == "help_options"
    assert low["safety"] <= 45 < high["safety"]
    assert "prepare_wheelchair_exit" in option_ids(medical, low)
    assert "prepare_wheelchair_exit" not in option_ids(medical, high)
    promised, _ = play(tablet, content, ["promise_check"])
    other, _ = play(tablet, content, ["acknowledge_ask"])
    assert "return_with_answer" in option_ids(tablet, promised)
    assert "return_with_answer" not in option_ids(tablet, other)
    warm, _ = play(tablet, content, ["acknowledge_ask", "explain_class", "offer_wifi", "move_to_rack"])
    cold, _ = play(tablet, content, ["refuse_flat", "explain_class", "offer_wifi", "move_to_rack"])
    assert (warm["loyalty"], cold["loyalty"]) == (65, 40)
    assert "thank_assure" in option_ids(tablet, warm)
    assert "thank_assure" not in option_ids(tablet, cold)


def test_event_continue(medical, content):
    state, _ = play(medical, content, ["give_own_pills"])
    assert state["node"] == "pills_taken" and state["deadline_at"] is None
    with pytest.raises(engine.EngineError) as caught:
        engine.apply_choice(medical, content, state, "water_and_calm", T0 + timedelta(seconds=10), GRACE)
    assert caught.value.code == "option_unavailable"
    state, step = engine.apply_choice(
        medical, content, state, engine.CONTINUE, T0 + timedelta(seconds=10), GRACE
    )
    assert step["option_id"] == engine.CONTINUE and state["node"] == "at_the_seat"
    assert state["safety"] == 30 and state["flags"] == {"pills_given": True}
    assert state["chosen"] == ["give_own_pills"]


def test_forced_outcome_incident(tablet, content):
    state, _ = play(tablet, content, ["acknowledge_ask", "explain_class", "offer_wifi", "leave_in_aisle"])
    assert state["node"] == "ending_luggage_fall" and state["status"] == "finished"
    assert state["safety"] == 45 >= content.rules["outcome"]["incident_if_safety_below"]
    assert state["outcome"] == "incident"


def test_outcomes_by_thresholds(tablet, medical, content):
    assert rules.outcome_thresholds(tablet, content.rules) == content.rules["outcome"]
    assert rules.outcome_thresholds(medical, content.rules)["exemplary_if"] == {
        "safety_min": 90,
        "loyalty_min": 80,
        "no_expired_timers": True,
    }
    exemplary, _ = play(
        tablet, content, ["acknowledge_ask", "explain_class", "offer_wifi", "move_to_rack", "thank_assure"]
    )
    assert (exemplary["loyalty"], exemplary["safety"], exemplary["outcome"]) == (70, 75, "exemplary")
    business, _ = play(
        tablet, content, ["acknowledge_ask", "bring_tablet", "move_to_rack", "thank_assure"], "business"
    )
    assert (business["loyalty"], business["outcome"]) == (88, "exemplary")
    expired, _ = play(
        tablet, content, ["expire", "continue", "explain_class", "offer_wifi", "move_to_rack", "just_leave"]
    )
    assert expired["outcome"] == "acceptable" and expired["expired_timers"] == 1


def test_competency_points_per_run(medical, content):
    state, _ = play(medical, content, BEST_PATH)
    assert state["timers_answered"] == 3
    assert state["earned"]["medical"] == 8
    # в assessed входят только показанные варианты: скрытые классом или прошлым верным ходом не упущены
    assert state["assessed"]["medical"] == 8
    assert state["assessed"]["rules"] == 2


def test_step_record_is_complete(medical, content):
    state, step = play(medical, content, ["call_chief_stay"])
    assert step == state["steps"][0]
    assert step["step_no"] == 1 and step["node_id"] == "intro" and step["next_node"] == "at_the_seat"
    assert step["effects"] == {"loyalty": 10, "safety": 10}
    assert step["competencies"] == {"medical": 2, "escalation": 2, "empathy": 1}
    assert (step["loyalty_before"], step["loyalty_after"]) == (60, 73)
    assert (step["safety_before"], step["safety_after"]) == (70, 80)
    assert step["timer_seconds"] == 20 and step["answered_in_seconds"] == 5.0
    assert step["delayed_applied"] == [] and step["expired"] is False


def test_deterministic_replay(medical, content):
    first, _ = play(medical, content, BEST_PATH)
    second, _ = play(medical, content, BEST_PATH)
    assert first == second
    expired_first, _ = play(medical, content, ["expire", "check_and_radio_chief"])
    expired_second, _ = play(medical, content, ["expire", "check_and_radio_chief"])
    assert expired_first == expired_second
    assert first["steps"][0]["answered_in_seconds"] == 5.0


def test_round_half_away():
    assert engine.round_half_away(12.5) == 13
    assert engine.round_half_away(-12.5) == -13
    assert engine.round_half_away(7.4) == 7
    assert engine.round_half_away(-6.25) == -6
