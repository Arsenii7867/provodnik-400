"""Перебор путей эталонного сценария: число путей и исходов, разброс шкал, условия показа,
концовки по классам и сравнение финалов с истечением и без."""

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


def test_every_class_is_enumerated(result, content):
    assert set(result["by_class"]) == set(content.classes)
    # чувствительность класса меняет только лояльность, поэтому число путей одинаково
    assert {item["paths"] for item in result["by_class"].values()} == {411}
    assert result["role_chain_possible"]


def test_timers_collect_finals_with_and_without_expiry(result):
    timers = result["own"]["timers"]
    assert set(timers) == {"intro", "help_options", "medic_found"}
    for node_id, timer in timers.items():
        expired = analysis.best_final(timer["expired_finals"])
        answered = analysis.best_final(timer["answered_finals"])
        assert analysis.final_key(expired) < analysis.final_key(answered), node_id
    assert analysis.best_final(timers["intro"]["answered_finals"]) == ("exemplary", 98, 100)


def test_final_order_prefers_outcome_over_scales():
    finals = {("incident", 100, 30), ("acceptable", 40, 45), ("acceptable", 60, 50)}
    assert analysis.best_final(finals) == ("acceptable", 60, 50)
    assert analysis.final_key(("exemplary", 70, 75)) > analysis.final_key(("acceptable", 100, 100))


def test_path_limit_marks_truncated(scenario, content):
    summary = analysis.enumerate_paths(scenario, content, limit=10)
    assert summary["truncated"]
    assert summary["paths"] == 10
