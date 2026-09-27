"""Реальный PostgreSQL: POSTGRES_TEST_URL задаётся только для отдельной тестовой БД.

Каждый тест создаёт собственную схему и удаляет только её; public не используется.
Запуск из backend: POSTGRES_TEST_URL=postgresql+psycopg://... .venv/bin/pytest -q compat_tests
Без переменной тесты пропускаются, подключения к SQLite или демо-базе нет.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app import clock, ratelimit
from app.config import Settings
from app.main import create_app
from app.models import (
    AchievementEarned,
    ActionLog,
    Base,
    BonusPoint,
    Challenge,
    Employee,
    Notification,
    OutboxEvent,
    Profile,
    RunStep,
    ScenarioRun,
)
from app.seed import seed

pytestmark = pytest.mark.skipif(not os.environ.get("POSTGRES_TEST_URL"), reason="POSTGRES_TEST_URL не задан")
MEDICAL_PATH = ["call_chief_stay", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"]
WHEELCHAIR_PATH = [
    "greet_passenger_first",
    "operate_lift_by_rules",
    "seat_and_fold_wheelchair",
    "help_place_luggage",
    "inform_chief_destination_assist",
    "offer_meal_to_seat",
]


@pytest.fixture
def postgres(tmp_path):
    url = make_url(os.environ["POSTGRES_TEST_URL"])
    if url.drivername != "postgresql+psycopg":
        pytest.fail("POSTGRES_TEST_URL должен использовать postgresql+psycopg")
    schema = f"compat_{uuid4().hex}"
    admin = create_engine(url, connect_args={"connect_timeout": 10})
    app = None
    created = False
    clock.freeze(datetime(2026, 9, 27, 6, 0, tzinfo=UTC))
    ratelimit.reset()
    try:
        with admin.begin() as db:
            db.execute(CreateSchema(schema))
        created = True
        scoped = url.update_query_dict(
            {"options": f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000"}
        )
        settings = Settings(
            database_url=scoped.render_as_string(hide_password=False),
            app_env="test",
            auto_seed=False,
            frontend_dist=tmp_path / "dist",
            integration_api_key="postgres-compat-test-only",
        )
        app = create_app(settings)
        with TestClient(app) as client:
            with app.state.session_factory() as db:
                assert db.scalar(text("SELECT current_schema()")) == schema
                assert seed(db, app.state.store, settings, clock.now(), history=False)
            yield app, client, schema
    finally:
        if app is not None:
            app.state.engine.dispose()
        try:
            if created:
                with admin.begin() as db:
                    db.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()
            clock.reset()
            ratelimit.reset()


def login(client, code="VSM-1001"):
    response = client.post("/api/auth/login", json={"employee_code": code, "pin": "1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def start(client, headers, scenario="medical_chest_pain"):
    response = client.post("/api/sessions", headers=headers, json={"scenario_id": scenario})
    assert response.status_code == 201, response.text
    return response.json()


def choose(client, headers, view, option):
    return client.post(
        f"/api/sessions/{view['run_id']}/choose",
        headers=headers,
        json={"step_no": view["step_no"], "option_id": option},
    )


def parallel_requests(request):
    barrier = threading.Barrier(2, timeout=10)

    def send(index):
        barrier.wait()
        return request(index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(send, range(2)))


def winning_choice(client, headers, view, option):
    responses = parallel_requests(lambda _: choose(client, headers, view, option))
    assert sorted(response.status_code for response in responses) == [200, 409], [
        response.text for response in responses
    ]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["error"]["code"] in {"stale_step", "already_finished"}
    return next(response.json() for response in responses if response.status_code == 200)


def test_schema_indexes_and_repeat_seed(postgres):
    app, _, schema = postgres
    assert app.state.engine.dialect.name == "postgresql"
    inspector = inspect(app.state.engine)
    assert set(inspector.get_table_names(schema=schema)) == set(Base.metadata.tables)
    indexes = inspector.get_indexes("scenario_runs", schema=schema)
    assert any(item["name"] == "ix_scenario_runs_employee_scenario_status" for item in indexes)
    constraints = inspector.get_unique_constraints("scenario_runs", schema=schema)
    assert any(item["column_names"] == ["employee_id", "idempotency_key"] for item in constraints)
    steps = inspector.get_unique_constraints("run_steps", schema=schema)
    assert any(item["column_names"] == ["run_id", "step_no"] for item in steps)
    with app.state.session_factory() as db:
        before = {
            table.name: db.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables
        }
        assert seed(db, app.state.store, app.state.settings, clock.now(), history=False) is False
        after = {
            table.name: db.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables
        }
        assert before == after
        assert before["employees"] > 2 and before["challenges"] == 3
        assert all(db.scalars(select(Employee.is_synthetic)))
        challenge = db.get(Challenge, "inclusion_week")
        assert challenge.scenario_ids_json == ["wheelchair_boarding"]
        assert challenge.starts_at == clock.now() and challenge.starts_at.tzinfo is UTC


def test_concurrent_idempotent_start(postgres):
    app, client, _ = postgres
    headers = login(client) | {"Idempotency-Key": "postgres-same-start"}
    responses = parallel_requests(
        lambda _: client.post("/api/sessions", headers=headers, json={"scenario_id": "medical_chest_pain"})
    )
    assert sorted(response.status_code for response in responses) == [200, 201], [
        response.text for response in responses
    ]
    assert len({response.json()["run_id"] for response in responses}) == 1
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ScenarioRun)) == 1
        run = db.scalar(select(ScenarioRun))
        assert run.status == "active" and run.idempotency_key == "postgres-same-start"
        assert (
            db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.action == "run_started"))
            == 1
        )
    conflict = client.post("/api/sessions", headers=headers, json={"scenario_id": "wheelchair_boarding"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_mismatch"


def test_concurrent_distinct_starts_keep_one_active_run(postgres):
    app, client, _ = postgres
    headers = login(client)
    responses = parallel_requests(
        lambda index: client.post(
            "/api/sessions",
            headers=headers | {"Idempotency-Key": f"postgres-distinct-{index}"},
            json={"scenario_id": "medical_chest_pain"},
        )
    )
    assert [response.status_code for response in responses] == [201, 201], [
        response.text for response in responses
    ]
    with app.state.session_factory() as db:
        runs = db.scalars(select(ScenarioRun)).all()
        assert len(runs) == 2
        assert sorted(run.status for run in runs) == ["abandoned", "active"]
        active_id = next(run.id for run in runs if run.status == "active")
    assert client.get("/api/sessions/active", headers=headers).json()["active"]["run_id"] == active_id


def test_concurrent_choices_finish_once_with_debrief_and_access_controls(postgres):
    app, client, _ = postgres
    headers, other = login(client), login(client, "VSM-1002")
    assert client.get("/api/profile").status_code == 401
    view = start(client, headers)
    forbidden = choose(client, other, view, MEDICAL_PATH[0])
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "foreign_run"
    assert client.get(f"/api/sessions/{view['run_id']}", headers=other).status_code == 403
    view = winning_choice(client, headers, view, MEDICAL_PATH[0])
    assert view["step_no"] == 1
    for option in MEDICAL_PATH[1:-1]:
        response = choose(client, headers, view, option)
        assert response.status_code == 200, response.text
        view = response.json()
    view = winning_choice(client, headers, view, MEDICAL_PATH[-1])
    assert view["status"] == "finished" and view["outcome"] == "exemplary"
    assert client.get(f"/api/runs/{view['run_id']}/debrief", headers=other).status_code == 403
    response = client.get(f"/api/runs/{view['run_id']}/debrief", headers=headers)
    assert response.status_code == 200, response.text
    debrief = response.json()
    assert debrief["xp"] == view["xp"] > 0 and len(debrief["steps"]) == len(MEDICAL_PATH)
    assert debrief["ending"]["refs"] and debrief["competencies_delta"]
    expected_awards = {"first_run", "four_steps", "cool_head", "safety_first"}
    assert {award["id"] for award in debrief["achievements_new"]} == expected_awards
    with app.state.session_factory() as db:
        run = db.get(ScenarioRun, view["run_id"])
        assert db.get(Profile, run.employee_id).xp_total == run.xp_earned == view["xp"]
        assert run.finished_at.tzinfo is UTC and run.state_json["status"] == "finished"
        steps = db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.step_no)).all()
        assert [step.option_id for step in steps] == MEDICAL_PATH
        assert set(db.scalars(select(AchievementEarned.achievement_id))) == expected_awards
        assert db.scalar(select(func.count()).select_from(AchievementEarned)) == len(expected_awards)
        completed = select(OutboxEvent).where(OutboxEvent.event_type == "run_completed")
        assert [event.payload_json["run_id"] for event in db.scalars(completed)] == [run.id]
        assert (
            db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.action == "run_finished"))
            == 1
        )
        assert db.scalar(
            select(func.count()).select_from(Notification).where(Notification.kind == "achievement")
        ) == len(expected_awards)


def test_concurrent_finish_awards_challenge_bonus_once(postgres):
    app, client, _ = postgres
    headers = login(client)
    view = start(client, headers, "wheelchair_boarding")
    for option in WHEELCHAIR_PATH[:-1]:
        response = choose(client, headers, view, option)
        assert response.status_code == 200, response.text
        view = response.json()
    view = winning_choice(client, headers, view, WHEELCHAIR_PATH[-1])
    response = client.get(f"/api/runs/{view['run_id']}/debrief", headers=headers)
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["challenges_completed"]] == ["inclusion_week"]
    with app.state.session_factory() as db:
        bonuses = db.scalars(select(BonusPoint)).all()
        assert len(bonuses) == 1
        assert bonuses[0].challenge_id == "inclusion_week" and bonuses[0].run_id == view["run_id"]
        assert bonuses[0].points == 40 and bonuses[0].expires_at > clock.now()
        completed = select(OutboxEvent).where(OutboxEvent.event_type == "challenge_completed")
        assert [event.payload_json["challenge_id"] for event in db.scalars(completed)] == ["inclusion_week"]
