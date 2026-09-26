"""Перебор путей эталонного сценария: число путей и исходов, разброс шкал, условия показа,
чувствительность класса, ветка истечения, отложенные последствия и ролевая цепочка."""

from pathlib import Path

import pytest

from app.scenarios import analysis
from app.scenarios.loader import load_content

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture(scope="module")
def content():
    return load_content(CONTENT_DIR)


@pytest.fixture(scope="module")
def scenario(content):
    return content.scenarios["medical_chest_pain"]


@pytest.fixture(scope="module")
def result(scenario, content):
    return analysis.analyze(scenario, content)


def walk(scenario, content, option_ids, service_class=None):
    state = analysis.start_state(scenario, content, service_class)
    for option_id in option_ids:
        if option_id == "expire":
            analysis.apply_expire_branch(scenario, content, state)
        else:
            analysis.apply_option(scenario, content, state, option_id)
    return state


def test_paths_and_outcomes_of_reference(result):
    own = result["own"]
    assert own["paths"] == 411
    assert not own["truncated"]
    assert set(own["outcomes"]) == {"exemplary", "acceptable", "incident"}
    assert set(own["endings"]) == {"ending_station_medics", "ending_help_late", "ending_incident_pills"}
    assert own["endings"]["ending_incident_pills"]["outcomes"] == {"incident": 16}
    assert own["corridor_share"] == 0.25


def test_scale_spread(result, content):
    own = result["own"]
    need = content.rules["analysis"]["min_scale_spread"]
    assert own["loyalty"]["max"] - own["loyalty"]["min"] >= need
    assert own["safety"]["max"] - own["safety"]["min"] >= need


def test_conditions_shown_and_hidden(result):
    for key in [
        ("help_options", "pa_medic"),
        ("help_options", "hide_pill"),
        ("medic_found", "tell_about_pill"),
    ]:
        assert key in result["shown"]
        assert key in result["hidden"]
    assert result["empty_nodes"] == set()


def test_class_changes_loyalty_delta(scenario, content):
    business = walk(scenario, content, ["call_chief_stay"])
    standard = walk(scenario, content, ["call_chief_stay"], service_class="standard")
    first = walk(scenario, content, ["call_chief_stay"], service_class="first")
    assert (standard["loyalty"], business["loyalty"], first["loyalty"]) == (70, 73, 75)
    assert standard["safety"] == business["safety"] == first["safety"] == 80


def test_expire_branch_leads_to_expire_only_node(scenario, content):
    state = walk(scenario, content, ["expire"])
    assert state["node"] == "collapsed"
    assert state["expired_timers"] == 1
    assert (state["loyalty"], state["safety"]) == (47, 50)
    assert all(option["next"] != "collapsed" for option in scenario["nodes"]["intro"]["options"])


def test_best_choices_after_expiry_stay_acceptable(scenario, content):
    state = walk(
        scenario,
        content,
        [
            "expire",
            "check_and_radio_chief",
            "water_and_calm",
            "pa_medic",
            "brief_medic_full",
            "announce_calm",
        ],
    )
    assert state["status"] == "finished"
    assert state["expired_timers"] == 1
    assert state["timers_answered"] == 2
    assert (state["loyalty"], state["safety"]) == (72, 80)
    assert state["outcome"] == "acceptable"


def test_trap_options_never_reach_exemplary(scenario, content):
    traps = [
        ["call_chief_stay", "ask_neighbors_for_pills", "pa_medic", "tell_about_pill", "announce_calm"],
        ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "loud_panic"],
        ["call_chief_stay", "leave_to_meet_chief", "pa_medic", "brief_medic", "announce_calm"],
        ["finish_trolley_first", "water_and_calm", "radio_chief_late", "announce_calm"],
    ]
    for path in traps:
        state = walk(scenario, content, path)
        assert state["status"] == "finished"
        assert state["outcome"] != "exemplary", path


def test_delayed_penalty_applies_unless_returned(scenario, content):
    returned = walk(scenario, content, ["run_for_chief", "water_and_calm", "request_station_medics"])
    left = walk(scenario, content, ["run_for_chief", "leave_to_meet_chief", "request_station_medics"])
    assert returned["flags"]["returned_to_passenger"] is True
    assert returned["delayed"] == []
    assert left["delayed"] == []
    # бизнес-класс: каждые минус 10 лояльности превращаются в минус 13 (10 x 1.25 с округлением от нуля)
    assert returned["loyalty"] == 60
    assert left["loyalty"] == 15


def test_delayed_step_reports_what_was_applied(scenario, content):
    state = walk(scenario, content, ["run_for_chief", "leave_to_meet_chief"])
    step = analysis.apply_option(scenario, content, state, "request_station_medics")
    [applied] = step["delayed_applied"]
    assert applied["option_id"] == "run_for_chief"
    assert applied["cancelled"] is False
    assert applied["effects"] == {"loyalty": -10}


def test_role_chain_on_best_path(scenario, content):
    state = walk(
        scenario,
        content,
        ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"],
    )
    assert state["role_chain"] == ["acknowledge", "rule", "solution", "assure"]
    assert analysis.role_chain_complete(state["role_chain"])
    assert (state["loyalty"], state["safety"]) == (98, 100)
    assert state["outcome"] == "exemplary"
    assert state["timers_answered"] == 3
    assert state["earned"]["medical"] == 7
    assert state["assessed"]["medical"] == 8


def test_role_chain_requires_order():
    assert analysis.role_chain_complete(["acknowledge", "solution", "rule", "solution", "assure"])
    assert not analysis.role_chain_complete(["rule", "acknowledge", "solution", "assure"])


def test_hidden_option_is_rejected(scenario, content):
    state = walk(scenario, content, ["finish_trolley_first", "water_and_calm"])
    with pytest.raises(ValueError):
        analysis.apply_option(scenario, content, state, "pa_medic")
    assert [option["id"] for option in analysis.available_options(scenario, state)] == [
        "radio_chief_late",
        "just_wait",
    ]


def test_forced_incident_ending(scenario, content):
    state = walk(scenario, content, ["give_own_pills", "continue", "water_and_calm", "hide_pill"])
    assert state["node"] == "ending_incident_pills"
    assert state["outcome"] == "incident"
    assert state["flags"]["pills_given"] is True


def test_round_half_away():
    assert analysis.round_half_away(12.5) == 13
    assert analysis.round_half_away(-12.5) == -13
    assert analysis.round_half_away(7.4) == 7
    assert analysis.round_half_away(-6.25) == -6
