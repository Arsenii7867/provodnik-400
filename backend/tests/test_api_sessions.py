"""API прохождения через TestClient: вход и лимиты, каталог, старт с идемпотентностью,
полный путь до концовки, серверные таймеры по подменённым часам, коды 401, 403, 404, 409, 422,
429 в едином формате."""

from datetime import datetime
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.auth import require_role
from app.main import create_app
from app.models import ActionLog, Employee, Profile, RunStep, ScenarioRun
from app.scenarios.engine import round_half_away

SCENARIO = "medical_chest_pain"
FIRST_TIMER_SECONDS = 20
BEST_PATH = ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"]
ERROR_KEYS = {"code", "message", "details"}


def error_code(response, status):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == ERROR_KEYS
    return body["error"]["code"]


def start(client, headers, scenario_id=SCENARIO, **extra):
    response = client.post("/api/sessions", json={"scenario_id": scenario_id}, headers=headers | extra)
    assert response.status_code == 201, response.text
    return response.json()


def choose(client, headers, view, option_id):
    return client.post(
        f"/api/sessions/{view['run_id']}/choose",
        json={"option_id": option_id, "step_no": view["step_no"]},
        headers=headers,
    )


def expire(client, headers, view):
    body = {"step_no": view["step_no"]}
    return client.post(f"/api/sessions/{view['run_id']}/expire", json=body, headers=headers)


def play_best_path(client, headers):
    view = start(client, headers)
    for option_id in BEST_PATH:
        response = choose(client, headers, view, option_id)
        assert response.status_code == 200, response.text
        view = response.json()
    return view


def test_login_wrong_pin_401(client):
    response = client.post("/api/auth/login", json={"employee_code": "VSM-1001", "pin": "0000"})
    assert error_code(response, 401) == "pin_invalid"
    unknown = client.post("/api/auth/login", json={"employee_code": "VSM-9999", "pin": "1234"})
    assert error_code(unknown, 401) == "pin_invalid"


def test_login_rate_limited(client, settings):
    for _ in range(settings.login_rate_per_minute):
        response = client.post("/api/auth/login", json={"employee_code": "VSM-1001", "pin": "0000"})
        assert response.status_code == 401
    blocked = client.post("/api/auth/login", json={"employee_code": "VSM-1001", "pin": settings.demo_pin})
    assert error_code(blocked, 429) == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
    clock.travel(61)
    allowed = client.post("/api/auth/login", json={"employee_code": "VSM-1001", "pin": settings.demo_pin})
    assert allowed.status_code == 200


def test_login_me_and_logout(client, login):
    headers = login()
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert (body["employee_code"], body["role"], body["brigade"]) == ("VSM-1001", "conductor", "М-01")
    assert body["depot"] == "ТЧ Москва-ВСМ" and body["display_name"]
    assert client.post("/api/auth/logout", headers=headers).json() == {"ok": True}
    assert error_code(client.get("/api/auth/me", headers=headers), 401) == "token_invalid"


def test_token_expired_401(client, login, settings):
    headers = login()
    clock.travel(settings.token_ttl_hours * 3600 + 1)
    assert error_code(client.get("/api/auth/me", headers=headers), 401) == "token_expired"


def test_missing_token_401(client):
    assert error_code(client.get("/api/scenarios"), 401) == "token_missing"
    bad = client.get("/api/scenarios", headers={"Authorization": "Bearer nope"})
    assert error_code(bad, 401) == "token_invalid"


def test_demo_accounts_listed_without_login(client):
    response = client.get("/api/auth/demo")
    assert response.status_code == 200
    codes = [item["employee_code"] for item in response.json()]
    assert codes == ["VSM-1001", "VSM-1002", "VSM-2001"]
    assert all(item["note"] for item in response.json())


def test_catalog_cards_and_filters(client, login):
    headers = login()
    cards = client.get("/api/scenarios", headers=headers).json()
    card = next(item for item in cards if item["id"] == SCENARIO)
    assert card["has_timers"] is True and card["critical"] is True
    assert card["service_class_title"] == "Бизнес"
    assert card["best_outcome"] is None and card["runs_count"] == 0
    assert len(card["competencies_titles"]) == len(card["competencies"])
    by_competency = client.get("/api/scenarios?competency=medical", headers=headers).json()
    assert SCENARIO in [item["id"] for item in by_competency]
    assert all("medical" in item["competencies"] for item in by_competency)
    by_class = client.get("/api/scenarios?service_class=business&critical=true", headers=headers).json()
    assert all(item["service_class"] == "business" and item["critical"] for item in by_class)
    assert client.get("/api/scenarios?competency=nonexistent", headers=headers).json() == []
    filters = client.get("/api/scenarios/filters", headers=headers).json()
    assert [item["code"] for item in filters["classes"]] == ["standard", "comfort", "business", "first"]
    assert filters["difficulties"] == [1, 2, 3, 4, 5]


def test_scenario_detail_and_404(client, login):
    headers = login()
    detail = client.get(f"/api/scenarios/{SCENARIO}", headers=headers).json()
    assert detail["paths"] > 0 and set(detail["outcomes"]) == {"incident", "acceptable", "exemplary"}
    assert detail["context"]["service_class"] == "business"
    assert detail["context"]["loyalty_sensitivity"] == 1.25
    assert detail["source_situations"] == [19, 28]
    assert error_code(client.get("/api/scenarios/nope", headers=headers), 404) == "scenario_not_found"


def test_start_returns_state_with_timer(client, login):
    headers = login()
    view = start(client, headers)
    assert view["status"] == "active" and view["step_no"] == 0
    assert view["node"]["id"] == "intro" and view["node"]["timer_seconds"] == FIRST_TIMER_SECONDS
    assert [option["id"] for option in view["node"]["options"]][:1] == ["call_chief_stay"]
    deadline = datetime.fromisoformat(view["deadline_at"])
    server_now = datetime.fromisoformat(view["server_now"])
    assert (deadline - server_now).total_seconds() == pytest.approx(FIRST_TIMER_SECONDS, abs=0.01)
    assert view["expired"] is False and view["last_step"] is None
    assert view["context"]["service_class_title"] == "Бизнес"
    assert view["role_chain"] == {"steps": [], "next_expected": "acknowledge", "complete": False}


def test_full_run_to_ending(client, login, app):
    headers = login()
    view = play_best_path(client, headers)
    assert view["status"] == "finished" and view["node"]["type"] == "ending"
    assert view["outcome"] == "exemplary" and view["xp"] > 0
    assert view["role_chain"]["complete"] is True
    assert view["node"]["options"] == [] and view["deadline_at"] is None
    assert view["last_step"]["option_id"] == "announce_calm"
    assert view["last_step"]["loyalty_after"] == view["loyalty"]
    cards = client.get("/api/scenarios", headers=headers).json()
    card = next(item for item in cards if item["id"] == SCENARIO)
    assert card["best_outcome"] == "exemplary" and card["runs_count"] == 1
    with app.state.session_factory() as db:
        run = db.get(ScenarioRun, view["run_id"])
        steps = db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.step_no)).all()
        profile = db.get(Profile, run.employee_id)
        actions = db.scalars(select(ActionLog).where(ActionLog.entity_id == str(run.id))).all()
    assert run.status == "finished" and run.score == run.xp_earned
    assert run.xp_breakdown_json["role"] > 0 and run.competencies_json["medical"]["assessed"] > 0
    assert [step.option_id for step in steps] == BEST_PATH
    assert steps[0].loyalty_before == 60 and steps[0].loyalty_after > 60
    assert steps[0].verdict == "best" and steps[0].role_step == "acknowledge"
    assert all(step.answered_in_seconds is not None for step in steps)
    assert profile.xp_total >= run.xp_earned
    assert {action.action for action in actions} == {"run_started", "option_chosen", "run_finished"}


def test_repeat_run_gives_half_xp(client, login):
    headers = login()
    first = play_best_path(client, headers)
    second = play_best_path(client, headers)
    assert second["xp"] == round_half_away(first["xp"] / 2)


def test_choice_after_deadline_rejected(client, login):
    headers = login()
    view = start(client, headers)
    clock.travel(FIRST_TIMER_SECONDS + 2)
    response = choose(client, headers, view, "call_chief_stay")
    assert response.status_code == 200, response.text
    late = response.json()
    assert late["expired"] is True and late["step_no"] == 1
    assert late["node"]["id"] == "collapsed"
    assert late["last_step"]["expired"] is True and late["last_step"]["option_id"] is None
    assert late["last_step"]["loyalty_after"] < late["last_step"]["loyalty_before"]
    assert late["expired_timers"] == 1 and late["timers_answered"] == 0
    again = client.get(f"/api/sessions/{view['run_id']}", headers=headers).json()
    assert again["expired"] is False and again["node"]["id"] == "collapsed"


def test_expire_before_deadline_rejected(client, login):
    headers = login()
    view = start(client, headers)
    response = expire(client, headers, view)
    assert error_code(response, 409) == "too_early"
    still = client.get(f"/api/sessions/{view['run_id']}", headers=headers).json()
    assert still["step_no"] == 0 and still["node"]["id"] == "intro"


def test_expire_after_deadline_applies_branch(client, login):
    headers = login()
    view = start(client, headers)
    clock.travel(FIRST_TIMER_SECONDS + 1)
    response = expire(client, headers, view)
    assert response.status_code == 200, response.text
    assert response.json()["expired"] is True and response.json()["node"]["id"] == "collapsed"
    assert error_code(expire(client, headers, response.json()), 409) == "no_timer"


def test_stale_step_rejected(client, login):
    headers = login()
    view = start(client, headers)
    stale = client.post(
        f"/api/sessions/{view['run_id']}/choose",
        json={"option_id": "call_chief_stay", "step_no": 5},
        headers=headers,
    )
    assert error_code(stale, 409) == "stale_step"
    assert choose(client, headers, view, "call_chief_stay").status_code == 200
    # двойной клик: тот же ход с прежним step_no
    assert error_code(choose(client, headers, view, "call_chief_stay"), 409) == "stale_step"


def test_unknown_option_rejected(client, login):
    headers = login()
    view = start(client, headers)
    assert error_code(choose(client, headers, view, "no_such_option"), 409) == "option_unavailable"


def test_foreign_run_forbidden(client, login):
    owner = login("VSM-1001")
    other = login("VSM-1002")
    view = start(client, owner)
    assert error_code(client.get(f"/api/sessions/{view['run_id']}", headers=other), 403) == "foreign_run"
    assert error_code(choose(client, other, view, "call_chief_stay"), 403) == "foreign_run"
    assert error_code(client.get("/api/sessions/999999", headers=owner), 404) == "run_not_found"


def test_error_format_is_uniform(client, login, settings):
    headers = login()
    view = start(client, headers)
    stale = {"option_id": "x", "step_no": 9}
    responses = [
        client.get("/api/scenarios"),
        client.get(f"/api/sessions/{view['run_id']}", headers=login("VSM-1002")),
        client.get("/api/sessions/999999", headers=headers),
        client.post(f"/api/sessions/{view['run_id']}/choose", json=stale, headers=headers),
        client.post("/api/sessions", json={"scenario_id": ""}, headers=headers),
        client.post("/api/auth/login", json={"employee_code": "VSM-1001"}),
    ]
    for _ in range(settings.login_rate_per_minute):
        client.post("/api/auth/login", json={"employee_code": "VSM-1001", "pin": "0000"})
    responses.append(client.post("/api/auth/login", json={"employee_code": "VSM-1001", "pin": "0000"}))
    assert [response.status_code for response in responses] == [401, 403, 404, 409, 422, 422, 429]
    for response in responses:
        body = response.json()
        assert set(body) == {"error"} and set(body["error"]) == ERROR_KEYS
        assert isinstance(body["error"]["details"], dict)
        assert "Traceback" not in response.text


def test_idempotent_start(client, login):
    headers = login()
    key = {"Idempotency-Key": "form-42"}
    first = client.post("/api/sessions", json={"scenario_id": SCENARIO}, headers=headers | key)
    second = client.post("/api/sessions", json={"scenario_id": SCENARIO}, headers=headers | key)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["run_id"] == second.json()["run_id"]
    other = client.post("/api/sessions", json={"scenario_id": "another"}, headers=headers | key)
    assert error_code(other, 409) == "idempotency_mismatch"
    foreign = client.post("/api/sessions", json={"scenario_id": SCENARIO}, headers=login("VSM-1002") | key)
    assert foreign.status_code == 201 and foreign.json()["run_id"] != first.json()["run_id"]


def test_new_start_abandons_previous(client, login):
    headers = login()
    first = start(client, headers)
    second = start(client, headers)
    previous = client.get(f"/api/sessions/{first['run_id']}", headers=headers).json()
    assert previous["status"] == "abandoned" and previous["node"]["options"] == []
    active = client.get("/api/sessions/active", headers=headers).json()["active"]
    assert active["run_id"] == second["run_id"]
    assert error_code(choose(client, headers, first, "call_chief_stay"), 409) == "already_finished"


def test_active_session_endpoint(client, login):
    headers = login()
    view = start(client, headers)
    abandoned = client.post(f"/api/sessions/{view['run_id']}/abandon", headers=headers)
    assert abandoned.status_code == 200 and abandoned.json()["status"] == "abandoned"
    assert client.get("/api/sessions/active", headers=headers).json() == {"active": None}
    again = client.post(f"/api/sessions/{view['run_id']}/abandon", headers=headers)
    assert error_code(again, 409) == "already_finished"


def test_finished_run_rejects_moves(client, login):
    headers = login()
    view = play_best_path(client, headers)
    assert error_code(choose(client, headers, view, "continue"), 409) == "already_finished"
    assert error_code(expire(client, headers, view), 409) == "already_finished"


def test_service_class_override(client, login):
    headers = login()
    body = {"scenario_id": SCENARIO, "service_class": "first"}
    response = client.post("/api/sessions", json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["context"]["service_class"] == "first"
    assert response.json()["context"]["loyalty_sensitivity"] == 1.5
    body["service_class"] = "lux"
    unknown = client.post("/api/sessions", json=body, headers=headers)
    assert error_code(unknown, 422) == "validation_error"
    missing = client.post("/api/sessions", json={"scenario_id": "nope"}, headers=headers)
    assert error_code(missing, 404) == "scenario_not_found"


def test_graph_locked_until_first_run(client, login):
    conductor = login("VSM-1001")
    mentor = login("VSM-2001")
    locked = client.get(f"/api/scenarios/{SCENARIO}/graph", headers=conductor)
    assert error_code(locked, 403) == "graph_locked"
    opened = client.get(f"/api/scenarios/{SCENARIO}/graph", headers=mentor)
    assert opened.status_code == 200 and opened.json()["mermaid"].startswith("flowchart TD")
    play_best_path(client, conductor)
    unlocked = client.get(f"/api/scenarios/{SCENARIO}/graph", headers=conductor).json()
    assert any(edge["kind"] == "expire" for edge in unlocked["edges"])
    assert unlocked["paths"] > 0 and "intro:" in unlocked["yaml_excerpt"]


@pytest.fixture
def mentor_only_client(settings):
    # маршрут-пробник для зависимости роли: первые маршруты только для наставника появятся позже
    app = create_app(settings)

    @app.get("/api/probe/mentor", include_in_schema=False)
    def mentor_probe(employee: Annotated[Employee, Depends(require_role("mentor"))]):
        return {"ok": True, "employee_code": employee.code}

    with TestClient(app) as client:
        yield client


def test_mentor_only_403(mentor_only_client, settings):
    def headers_for(code):
        body = {"employee_code": code, "pin": settings.demo_pin}
        token = mentor_only_client.post("/api/auth/login", json=body).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    denied = mentor_only_client.get("/api/probe/mentor", headers=headers_for("VSM-1001"))
    assert error_code(denied, 403) == "role_required"
    allowed = mentor_only_client.get("/api/probe/mentor", headers=headers_for("VSM-2001"))
    assert allowed.status_code == 200
