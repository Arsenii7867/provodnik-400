"""Формула XP и рейтинга, половина за повтор, уровни на границах порогов, владение и статусы
компетенций по окну прохождений; числа приходят из rules.yaml и levels.yaml, и правка копии
справочника меняет исход движка без правки кода."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.scenarios import engine
from app.scenarios.loader import load_content
from app.services import scoring

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
T0 = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def content():
    return load_content(CONTENT_DIR)


def run(scenario_id, earned, assessed):
    return {"scenario_id": scenario_id, "earned": earned, "assessed": assessed}


def replay(scenario, content, moves):
    now = T0
    state = engine.start(scenario, content, now)
    for move in moves:
        now += timedelta(seconds=3)
        state, _ = engine.apply_choice(scenario, content, state, move, now)
    return state


def test_xp_formula_examples(content):
    rules = content.rules
    best = scoring.xp_breakdown("exemplary", 98, 100, 3, True, rules)
    # (98 + 100) / 4 = 49.5, округление от нуля даёт 50
    assert best == {"base": 100, "scales": 50, "tempo": 15, "role": 20}
    assert scoring.score_of(best) == 185
    middle = scoring.xp_breakdown("acceptable", 72, 80, 2, False, rules)
    assert middle == {"base": 60, "scales": 38, "tempo": 10, "role": 0}
    poor = scoring.xp_breakdown("incident", 15, 5, 0, False, rules)
    assert poor == {"base": 20, "scales": 5, "tempo": 0, "role": 0}
    assert scoring.score_of(poor) == 25


def test_role_bonus_requires_complete_chain(content):
    best = ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"]
    state = replay(content.scenarios["medical_chest_pain"], content, best)
    complete = engine.role_chain_complete(state["role_chain"])
    breakdown = scoring.xp_breakdown(
        state["outcome"], state["loyalty"], state["safety"], state["timers_answered"], complete, content.rules
    )
    assert breakdown == {"base": 100, "scales": 50, "tempo": 15, "role": 20}
    partial = replay(content.scenarios["medical_chest_pain"], content, best[:1] + ["ask_history_only"])
    assert not engine.role_chain_complete(partial["role_chain"])
    assert scoring.xp_breakdown("acceptable", 70, 70, 2, False, content.rules)["role"] == 0


def test_xp_repeat_half(content):
    assert scoring.xp_for(185, False, content.rules) == 185
    assert scoring.xp_for(185, True, content.rules) == 93
    assert scoring.xp_for(108, True, content.rules) == 54


def test_level_thresholds(content):
    levels = content.levels
    assert scoring.level_for(0, levels) == {
        "id": "trainee",
        "title": "Стажёр",
        "threshold": 0,
        "next_threshold": 150,
        "next_title": "Проводник",
    }
    assert scoring.level_for(149, levels)["id"] == "trainee"
    assert scoring.level_for(150, levels)["id"] == "conductor"
    assert scoring.level_for(150, levels)["next_threshold"] == 400
    assert scoring.level_for(799, levels)["id"] == "senior"
    top = scoring.level_for(1400, levels)
    assert (top["id"], top["next_threshold"], top["next_title"]) == ("expert", None, None)
    assert scoring.level_for(5000, levels)["id"] == "expert"


def test_mastery_statuses(content):
    rules = content.rules
    runs = [
        run("smoking", {"medical": 1}, {"medical": 8}),
        run("medical", {"medical": 6, "empathy": 1}, {"medical": 8, "empathy": 3}),
        # более раннее прохождение того же сценария в окно не входит
        run("medical", {"medical": 8}, {"medical": 8}),
    ]
    by_code = {
        item["code"]: item
        for item in scoring.mastery_by_competency(runs, ["medical", "empathy", "rules"], rules)
    }
    assert by_code["medical"]["runs_assessed"] == 2
    assert by_code["medical"]["mastery"] == 7 / 16
    assert by_code["medical"]["status"] == "weak"
    assert by_code["empathy"] == {
        "code": "empathy",
        "earned": 1,
        "assessed": 3,
        "runs_assessed": 1,
        "mastery": 1 / 3,
        "status": "few_data",
    }
    assert by_code["rules"]["status"] == "gap" and by_code["rules"]["mastery"] is None
    strong = [run("a", {"medical": 6}, {"medical": 8}), run("b", {"medical": 4}, {"medical": 8})]
    assert scoring.mastery_by_competency(strong, ["medical"], rules)[0]["status"] == "ok"


def test_mastery_window_limits_runs(content):
    rules = content.rules
    window = rules["mastery"]["window_runs"]
    recent = [run(f"s{index}", {"rules": 3}, {"rules": 3}) for index in range(window)]
    older = [run("old_a", {"rules": 0}, {"rules": 3}), run("old_b", {"rules": 0}, {"rules": 3})]
    [item] = scoring.mastery_by_competency(recent + older, ["rules"], rules)
    assert item["runs_assessed"] == window and item["mastery"] == 1.0


def test_competency_status_edges(content):
    rules = content.rules
    assert scoring.competency_status(None, 0, rules) == "gap"
    assert scoring.competency_status(0.2, 1, rules) == "few_data"
    assert scoring.competency_status(0.49, 2, rules) == "weak"
    assert scoring.competency_status(0.5, 2, rules) == "ok"
    assert scoring.mastery(0, 0) is None


def test_rules_defaults_from_yaml(tmp_path, content):
    shutil.copytree(CONTENT_DIR, tmp_path / "content")
    path = tmp_path / "content" / "rules.yaml"
    text = path.read_text(encoding="utf-8")
    assert "incident_if_safety_below: 40" in text and "exemplary: 100" in text and "safety_min: 75" in text
    text = text.replace("incident_if_safety_below: 40", "incident_if_safety_below: 60")
    text = text.replace("exemplary: 100", "exemplary: 130")
    text = text.replace("safety_min: 75", "safety_min: 100")
    path.write_text(text, encoding="utf-8")
    changed = load_content(tmp_path / "content")
    path = ["finish_trolley_first", "ask_history_only", "just_wait"]
    original = replay(content.scenarios["medical_chest_pain"], content, path)
    stricter = replay(changed.scenarios["medical_chest_pain"], changed, path)
    assert original["safety"] == stricter["safety"] == 55
    assert (original["outcome"], stricter["outcome"]) == ("acceptable", "incident")
    assert scoring.xp_breakdown("exemplary", 90, 90, 0, False, changed.rules)["base"] == 130
    # outcome_rules сценария старше умолчаний: образцовый порог эталона остаётся 90
    best = ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"]
    assert replay(changed.scenarios["medical_chest_pain"], changed, best)["outcome"] == "exemplary"
