"""Интеграция для HR и LMS по X-API-Key: без ключа 401, результаты сотрудника, экспорт с
курсором и фильтром since, события с курсором и подтверждением, журнал действий, справочник
компетенций, создание сотрудника с одноразовым PIN."""

from datetime import timedelta
from urllib.parse import quote

from sqlalchemy import select

from app import clock
from app.models import Employee, OutboxEvent, Profile
from app.seed import CONDUCTORS_PER_BRIGADE
from tests.test_api_progress import play_expired_path
from tests.test_api_sessions import error_code, play_best_path

KEY = {"X-API-Key": "demo-integration-key"}


def test_key_required_401(client, login):
    missing = client.get("/api/integration/results")
    assert error_code(missing, 401) == "api_key_required"
    wrong = client.get("/api/integration/results", headers={"X-API-Key": "another-key"})
    assert error_code(wrong, 401) == "api_key_invalid"
    # символ вне ASCII в заголовке это тоже неверный ключ, а не сбой сравнения
    odd = client.get(
        "/api/integration/results", headers={"X-API-Key": "demo-integration-k\xe9y".encode("latin-1")}
    )
    assert error_code(odd, 401) == "api_key_invalid"
    # токен сотрудника интеграцию не открывает: у HR и LMS свой ключ
    bearer = client.get("/api/integration/competencies", headers=login("VSM-2001"))
    assert error_code(bearer, 401) == "api_key_required"
    for path in ("/api/integration/events", "/api/integration/employees/VSM-1001/results"):
        assert error_code(client.get(path), 401) == "api_key_required"
    assert (
        error_code(client.post("/api/integration/events/ack", json={"ids": [1]}), 401) == "api_key_required"
    )


def test_results_export_cursor(client, login):
    first = login("VSM-1001")
    second = login("VSM-1002")
    started = clock.now()
    views = [play_best_path(client, first), play_best_path(client, second), play_expired_path(client, first)]
    page = client.get("/api/integration/results?limit=2", headers=KEY).json()
    assert [item["run_id"] for item in page["items"]] == [views[0]["run_id"], views[1]["run_id"]]
    assert page["next_cursor"] == views[1]["run_id"]
    item = page["items"][0]
    assert item["employee_code"] == "VSM-1001" and item["brigade"] == "М-01"
    assert item["scenario_id"] == "medical_chest_pain" and item["scenario_version"] >= 1
    assert item["outcome"] == "exemplary" and item["score"] == 185 and item["xp"] == 185
    assert item["competencies"]["medical"] == {"earned": 8, "assessed": 8} and item["finished_at"]
    assert page["items"][1]["employee_code"] == "VSM-1002"
    rest = client.get(f"/api/integration/results?limit=2&cursor={page['next_cursor']}", headers=KEY).json()
    assert [item["run_id"] for item in rest["items"]] == [views[2]["run_id"]] and rest["next_cursor"] is None
    assert rest["items"][0]["outcome"] == "acceptable"
    since = clock.iso(started + timedelta(hours=1)).replace("+00:00", "Z")
    assert client.get(f"/api/integration/results?since={since}", headers=KEY).json() == {
        "items": [],
        "next_cursor": None,
    }
    # плюс в смещении часового пояса в адресе кодируется, иначе он превратится в пробел
    early = quote(clock.iso(started - timedelta(hours=1)))
    assert len(client.get(f"/api/integration/results?since={early}", headers=KEY).json()["items"]) == 3
    assert error_code(client.get("/api/integration/results?limit=0", headers=KEY), 422) == "validation_error"
    assert (
        error_code(client.get("/api/integration/results?since=вчера", headers=KEY), 422) == "validation_error"
    )


def test_employee_results(client, login):
    headers = login("VSM-1001")
    empty = client.get("/api/integration/employees/VSM-1001/results", headers=KEY).json()
    assert empty["runs"] == [] and empty["achievements"] == [] and empty["xp_total"] == 0
    assert empty["level"]["id"] == "trainee"
    assert all(item["status"] == "gap" and item["mastery"] is None for item in empty["competencies"])
    view = play_best_path(client, headers)
    body = client.get("/api/integration/employees/VSM-1001/results", headers=KEY).json()
    assert body["employee_code"] == "VSM-1001" and body["role"] == "conductor" and body["brigade"] == "М-01"
    assert body["depot"] == "ТЧ Москва-ВСМ" and body["display_name"]
    assert body["xp_total"] == 185 and body["level"]["id"] == "conductor"
    by_code = {item["code"]: item for item in body["competencies"]}
    assert by_code["medical"] == {"code": "medical", "mastery": 1.0, "status": "few_data", "runs_assessed": 1}
    assert by_code["inclusion"]["status"] == "gap"
    assert [run["run_id"] for run in body["runs"]] == [view["run_id"]]
    assert body["runs"][0]["score"] == 185 and body["runs"][0]["outcome"] == "exemplary"
    assert {item["id"] for item in body["achievements"]} == {
        "first_run",
        "four_steps",
        "cool_head",
        "safety_first",
    }
    assert all(item["earned_at"] for item in body["achievements"])
    missing = client.get("/api/integration/employees/VSM-9999/results", headers=KEY)
    assert error_code(missing, 404) == "employee_not_found"


def test_events_cursor_and_ack(client, login):
    play_best_path(client, login("VSM-1001"))
    first = client.get("/api/integration/events?limit=2", headers=KEY).json()
    assert [item["id"] for item in first["items"]] == [1, 2] and first["next_after_id"] == 2
    assert first["items"][0]["event_type"] == "run_completed"
    assert (
        first["items"][0]["payload"]["employee_code"] == "VSM-1001"
        and first["items"][0]["delivered_at"] is None
    )
    rest = client.get(
        f"/api/integration/events?after_id={first['next_after_id']}&limit=50", headers=KEY
    ).json()
    assert rest["items"][0]["id"] == 3 and rest["next_after_id"] == rest["items"][-1]["id"]
    kinds = [item["event_type"] for item in first["items"] + rest["items"]]
    assert kinds.count("achievement_earned") == 4 and kinds.count("level_up") == 1
    empty = client.get(f"/api/integration/events?after_id={rest['next_after_id']}", headers=KEY).json()
    assert empty == {"items": [], "next_after_id": rest["next_after_id"]}
    assert client.post("/api/integration/events/ack", json={"ids": [1, 2]}, headers=KEY).json() == {
        "acked": 2
    }
    assert client.post("/api/integration/events/ack", json={"ids": [1, 2, 999]}, headers=KEY).json() == {
        "acked": 0
    }
    again = client.get("/api/integration/events?limit=3", headers=KEY).json()
    assert [bool(item["delivered_at"]) for item in again["items"]] == [True, True, False]
    assert (
        error_code(client.post("/api/integration/events/ack", json={"ids": []}, headers=KEY), 422)
        == "validation_error"
    )
    huge = client.post("/api/integration/events/ack", json={"ids": [2**63]}, headers=KEY)
    assert error_code(huge, 422) == "validation_error"


def test_action_log_exported(client, login):
    headers = login("VSM-1001")
    play_best_path(client, headers)
    page = client.get("/api/integration/employees/VSM-1001/actions?limit=3", headers=KEY).json()
    assert [item["action"] for item in page["items"]] == ["login", "run_started", "option_chosen"]
    assert (
        page["items"][1]["entity_type"] == "run"
        and page["items"][1]["payload"]["scenario_id"] == "medical_chest_pain"
    )
    assert page["items"][2]["payload"]["option_id"] == "call_chief_stay" and page["items"][2]["created_at"]
    rest = client.get(
        f"/api/integration/employees/VSM-1001/actions?after_id={page['next_after_id']}", headers=KEY
    ).json()
    actions = [item["action"] for item in rest["items"]]
    assert actions[-1] == "run_finished" and actions.count("option_chosen") == 4
    assert rest["items"][-1]["payload"]["achievements"] == [
        "first_run",
        "four_steps",
        "cool_head",
        "safety_first",
    ]
    assert rest["items"][-1]["payload"]["level_up"] == "conductor"
    assert client.get("/api/integration/employees/VSM-1002/actions", headers=KEY).json() == {
        "items": [],
        "next_after_id": 0,
    }


def test_competencies_catalog(client):
    items = client.get("/api/integration/competencies", headers=KEY).json()
    assert [item["code"] for item in items] == [
        "empathy",
        "rules",
        "solution",
        "safety",
        "escalation",
        "medical",
        "inclusion",
    ]
    assert items[0]["title"] == "Эмпатия и контакт" and items[0]["description"]


def test_create_employee(client, app):
    body = {"employee_code": "VSM-1777", "display_name": "Новый проводник из HR", "brigade": "С-02"}
    created = client.post("/api/integration/employees", json=body, headers=KEY)
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["employee_code"] == "VSM-1777" and payload["role"] == "conductor"
    assert payload["brigade"] == "С-02" and payload["depot"] == "ТЧ Санкт-Петербург-ВСМ"
    assert len(payload["pin"]) == 4 and payload["pin"].isdigit()
    assert created.headers["Cache-Control"] == "no-store"
    # новый сотрудник сразу входит своим PIN и видит пустой профиль
    login_body = {"employee_code": "VSM-1777", "pin": payload["pin"]}
    token = client.post("/api/auth/login", json=login_body).json()["token"]
    fresh = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/profile", headers=fresh).json()
    # идущие челленджи объявлены и новичку: условия для него те же
    announced = [
        item for item in client.get("/api/notifications", headers=fresh).json() if item["kind"] == "challenge"
    ]
    assert {item["payload"]["challenge_id"] for item in announced} == {
        "safety_week",
        "four_steps_week",
        "inclusion_week",
    }
    assert announced[0]["body"].endswith("действует 7 дней после выполнения.")
    # новичок без очков делит ноль с шестью проводниками бригады и стоит последним по коду
    assert profile["xp_total"] == 0 and profile["brigade"] == "С-02"
    assert profile["rank_brigade"] == CONDUCTORS_PER_BRIGADE + 1
    results = client.get("/api/integration/employees/VSM-1777/results", headers=KEY).json()
    assert results["display_name"] == "Новый проводник из HR" and results["runs"] == []
    assert (
        error_code(client.post("/api/integration/employees", json=body, headers=KEY), 409)
        == "employee_exists"
    )
    unknown = client.post(
        "/api/integration/employees",
        json=body | {"employee_code": "VSM-1778", "brigade": "Я-99"},
        headers=KEY,
    )
    assert error_code(unknown, 404) == "brigade_not_found"
    bad_code = client.post(
        "/api/integration/employees", json=body | {"employee_code": "код с пробелом"}, headers=KEY
    )
    assert error_code(bad_code, 422) == "validation_error"
    bad_role = client.post(
        "/api/integration/employees", json=body | {"employee_code": "VSM-1779", "role": "admin"}, headers=KEY
    )
    assert error_code(bad_role, 422) == "validation_error"
    mentor = client.post(
        "/api/integration/employees",
        json={
            "employee_code": "VSM-2777",
            "display_name": "Наставник из HR",
            "brigade": "М-02",
            "role": "mentor",
        },
        headers=KEY,
    )
    assert mentor.status_code == 201 and mentor.json()["role"] == "mentor"
    with app.state.session_factory() as db:
        employee = db.scalar(select(Employee).where(Employee.code == "VSM-1777"))
        assert employee.is_synthetic is False and db.get(Profile, employee.id) is not None
        events = db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "employee_created")).all()
        assert [event.payload_json["employee_code"] for event in events] == ["VSM-1777", "VSM-2777"]
