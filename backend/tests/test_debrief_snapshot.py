"""Historical debriefs survive content edits, deletions and pre-snapshot runs."""

import copy
import dataclasses
import shutil
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.main import create_app
from app.models import Base, Challenge, ScenarioRun
from app.scenarios import refs
from app.services import debrief
from tests.test_api_sessions import BEST_PATH, SCENARIO, choose, error_code, play_best_path, start

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture
def app(settings, tmp_path):
    content_dir = tmp_path / "editable-content"
    shutil.copytree(CONTENT_DIR, content_dir)
    return create_app(dataclasses.replace(settings, content_dir=content_dir))


def read_yaml(app, name):
    return yaml.safe_load((app.state.store.content_dir / name).read_text(encoding="utf-8"))


def write_yaml(app, name, value):
    (app.state.store.content_dir / name).write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def reload_valid_content(app):
    report = app.state.store.reload()
    assert not report["errors"], report


def get_debrief(client, headers, run_id):
    response = client.get(f"/api/runs/{run_id}/debrief", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def finish_remaining(client, headers, view):
    for option_id in BEST_PATH[view["step_no"] :]:
        response = choose(client, headers, view, option_id)
        assert response.status_code == 200, response.text
        view = response.json()
    assert view["status"] == "finished"
    return view


def remove_snapshots(app, run_id):
    """Simulate a stored run written by the version before teaching snapshots existed."""
    with app.state.session_factory() as db:
        run = db.get(ScenarioRun, run_id)
        state = copy.deepcopy(run.state_json)
        state.pop("debrief_snapshot", None)
        for step in state["steps"]:
            step.pop("teaching_snapshot", None)
        run.state_json = state
        db.commit()


def remove_scenario(app):
    (app.state.store.content_dir / "scenarios" / f"{SCENARIO}.yaml").unlink()
    challenges = read_yaml(app, "challenges.yaml")
    for challenge in challenges:
        challenge["scenario_ids"] = [key for key in challenge["scenario_ids"] if key != SCENARIO]
    write_yaml(app, "challenges.yaml", challenges)
    reload_valid_content(app)
    assert SCENARIO not in app.state.store.content().scenarios


def database_contents(app):
    with app.state.session_factory() as db:
        return {
            table.name: [
                dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()
            ]
            for table in Base.metadata.sorted_tables
        }


def test_finished_debrief_survives_all_reference_edits_and_scenario_removal(app, client, login):
    headers = login()
    # Make this completion include a real challenge award as well as achievements/competencies.
    with app.state.session_factory() as db:
        challenge = db.get(Challenge, "four_steps_week")
        challenge.condition_json = {"type": "role_chain_count", "params": {"count": 1}}
        db.commit()
    run = play_best_path(client, headers)
    before = get_debrief(client, headers, run["run_id"])
    assert before["achievements_new"] and before["challenges_completed"] and before["competencies_delta"]
    assert any(step["refs"] for step in before["steps"])

    scenario = read_yaml(app, f"scenarios/{SCENARIO}.yaml")
    scenario["title"] = "Новая редакция сценария"
    for node in scenario["nodes"].values():
        node["text"] = "Новая редакция: " + node["text"]
        if "passenger_says" in node:
            node["passenger_says"] = "Новая реплика пассажира"
        if "title" in node:
            node["title"] = "Новое название концовки"
        for source in [node, *node.get("options", [])]:
            debrief = source.get("debrief", {})
            for field in ("why", "better", "summary"):
                if field in debrief:
                    debrief[field] = "Новая редакция учебного текста: " + debrief[field]
    write_yaml(app, f"scenarios/{SCENARIO}.yaml", scenario)
    references = read_yaml(app, "refs.yaml")
    for reference in references.values():
        for field in ("title", "quote", "rule", "phrase", "tip"):
            if field in reference:
                reference[field] = "Новая редакция нормы"
    write_yaml(app, "refs.yaml", references)
    for name in ("levels", "achievements", "competencies", "challenges"):
        items = read_yaml(app, f"{name}.yaml")
        for item in items:
            item["title"] = "Новое название " + item["title"]
            if "description" in item:
                item["description"] = "Новое описание"
        write_yaml(app, f"{name}.yaml", items)
    rules = read_yaml(app, "rules.yaml")
    rules["xp"]["base"]["exemplary"] += 70
    rules["mastery"]["min_runs_assessed"] = 1
    write_yaml(app, "rules.yaml", rules)
    reload_valid_content(app)
    assert app.state.store.content().scenarios[SCENARIO]["title"] == "Новая редакция сценария"

    assert get_debrief(client, headers, run["run_id"]) == before
    remove_scenario(app)
    assert get_debrief(client, headers, run["run_id"]) == before
    assert before["history_status"] == "snapshot"
    assert all(step["history_status"] == "snapshot" for step in before["steps"])


def test_step_teaching_is_saved_when_chosen_not_when_the_run_finishes(app, client, login):
    headers = login()
    content = app.state.store.content()
    intro = content.scenarios[SCENARIO]["nodes"]["intro"]
    chosen = next(item for item in intro["options"] if item["id"] == BEST_PATH[0])
    original_why = chosen["debrief"]["why"]
    original_refs = refs.describe_many(content.refs, chosen["debrief"]["refs"])
    original_passenger = intro.get("passenger_says")
    run = start(client, headers)
    response = choose(client, headers, run, BEST_PATH[0])
    assert response.status_code == 200, response.text
    run = response.json()
    scenario = read_yaml(app, f"scenarios/{SCENARIO}.yaml")
    first = next(item for item in scenario["nodes"]["intro"]["options"] if item["id"] == BEST_PATH[0])
    first["debrief"]["why"] = "Переписанное объяснение после сделанного выбора: " + original_why
    scenario["nodes"]["intro"]["passenger_says"] = "Другая реплика после сделанного выбора"
    write_yaml(app, f"scenarios/{SCENARIO}.yaml", scenario)
    references = read_yaml(app, "refs.yaml")
    for key in first["debrief"]["refs"]:
        references[key]["title"] = "Переписанная ссылка"
    write_yaml(app, "refs.yaml", references)
    reload_valid_content(app)
    finish_remaining(client, headers, run)
    data = get_debrief(client, headers, run["run_id"])
    assert data["steps"][0]["why"] == original_why
    assert data["steps"][0]["refs"] == original_refs
    assert data["steps"][0]["passenger_says"] == original_passenger
    assert data["history_status"] == "snapshot"


def test_legacy_finished_run_without_yaml_keeps_recorded_steps_and_get_is_read_only(app, client, login):
    headers = login()
    run = play_best_path(client, headers)
    original = get_debrief(client, headers, run["run_id"])
    remove_snapshots(app, run["run_id"])
    remove_scenario(app)
    before = database_contents(app)
    legacy = get_debrief(client, headers, run["run_id"])
    assert legacy["history_status"] == "legacy"
    assert len(legacy["steps"]) == len(original["steps"])
    for saved, restored in zip(original["steps"], legacy["steps"], strict=True):
        assert restored["history_status"] == "legacy"
        for field in (
            "step_no",
            "node_text",
            "option_text",
            "verdict",
            "loyalty_after",
            "safety_after",
            "timer_seconds",
        ):
            assert restored[field] == saved[field]
        assert restored["why"] is None and restored["refs"] == []
    assert get_debrief(client, headers, run["run_id"]) == legacy
    assert database_contents(app) == before


def test_preexisting_active_run_finishes_with_explicit_partial_history(app, client, login):
    headers = login()
    run = start(client, headers)
    response = choose(client, headers, run, BEST_PATH[0])
    assert response.status_code == 200, response.text
    run = response.json()
    remove_snapshots(app, run["run_id"])
    finish_remaining(client, headers, run)
    before = get_debrief(client, headers, run["run_id"])
    assert before["history_status"] == "partial"
    assert before["steps"][0]["history_status"] == "legacy"
    assert all(step["history_status"] == "snapshot" for step in before["steps"][1:])
    remove_scenario(app)
    assert get_debrief(client, headers, run["run_id"]) == before


def test_snapshot_get_is_read_only_and_still_checks_owner_and_completion(app, client, login):
    owner = login()
    foreign = login("VSM-1002")
    run = start(client, owner)
    path = f"/api/runs/{run['run_id']}/debrief"
    assert error_code(client.get(path, headers=owner), 409) == "run_not_finished"
    assert client.get(path, headers=foreign).status_code == 403
    finish_remaining(client, owner, run)
    before = database_contents(app)
    first = get_debrief(client, owner, run["run_id"])
    assert first["history_status"] == "snapshot"
    assert get_debrief(client, owner, run["run_id"]) == first
    assert client.get(path, headers=foreign).status_code == 403
    assert database_contents(app) == before


def test_failed_snapshot_rolls_back_completion_and_allows_safe_retry(app, client, login, monkeypatch):
    headers = login()
    run = start(client, headers)
    for option_id in BEST_PATH[:-1]:
        response = choose(client, headers, run, option_id)
        assert response.status_code == 200, response.text
        run = response.json()
    before = database_contents(app)

    def fail_snapshot(*args, **kwargs):
        raise RuntimeError("simulated snapshot storage failure")

    with monkeypatch.context() as fault:
        fault.setattr(debrief, "capture_response", fail_snapshot)
        with pytest.raises(RuntimeError, match="simulated snapshot storage failure"):
            choose(client, headers, run, BEST_PATH[-1])
    assert database_contents(app) == before
    response = choose(client, headers, run, BEST_PATH[-1])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "finished"
    result = get_debrief(client, headers, run["run_id"])
    assert result["history_status"] == "snapshot"
    assert len(result["steps"]) == len(BEST_PATH)


def test_finished_snapshot_can_be_read_when_content_store_is_unavailable(app, client, login, monkeypatch):
    headers = login()
    run = play_best_path(client, headers)
    expected = get_debrief(client, headers, run["run_id"])

    def unavailable():
        raise RuntimeError("content store unavailable")

    monkeypatch.setattr(app.state.store, "content", unavailable)
    assert get_debrief(client, headers, run["run_id"]) == expected


@pytest.mark.parametrize("finished", [False, True], ids=["unknown-step-version", "unknown-final-version"])
def test_unknown_snapshot_versions_have_explicit_fallback_without_get_writes(app, client, login, finished):
    headers = login()
    if finished:
        run = play_best_path(client, headers)
    else:
        run = start(client, headers)
        response = choose(client, headers, run, BEST_PATH[0])
        assert response.status_code == 200, response.text
        run = response.json()
    with app.state.session_factory() as db:
        row = db.get(ScenarioRun, run["run_id"])
        state = copy.deepcopy(row.state_json)
        if finished:
            state["debrief_snapshot"]["version"] = 999
        for step in state["steps"]:
            step["teaching_snapshot"]["version"] = 999
        row.state_json = state
        db.commit()
    if not finished:
        finish_remaining(client, headers, run)
    before = database_contents(app)
    result = get_debrief(client, headers, run["run_id"])
    assert result["history_status"] == ("legacy" if finished else "partial")
    assert result["steps"][0]["history_status"] == "legacy"
    if not finished:
        assert all(step["history_status"] == "snapshot" for step in result["steps"][1:])
    assert database_contents(app) == before
