"""Замкнутый цикл после завершения прохождения: XP и уровень в профиле, достижения по правилам
из achievements.yaml, уведомления с дедупликацией, события outbox с курсором, владение
компетенциями и разбор с цитатами норм; новая запись в achievements.yaml видна без перезапуска."""

import dataclasses
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.main import create_app
from app.models import AchievementEarned, EmployeeCompetency, Notification, OutboxEvent, Profile, ScenarioRun
from app.scenarios.loader import load_content
from app.services import achievements, notifications, outbox
from tests.test_api_sessions import (
    BEST_PATH,
    FIRST_TIMER_SECONDS,
    choose,
    error_code,
    expire,
    play_best_path,
    start,
)

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
# первый таймер истекает, дальше лучшие ходы, но цепочка без шага «признать» и таймер истёк
EXPIRED_PATH = ["check_and_radio_chief", "water_and_calm", "pa_medic", "brief_medic_full", "announce_calm"]
BEST_PATH_ACHIEVEMENTS = {"first_run", "four_steps", "cool_head", "safety_first"}
NEW_ACHIEVEMENT = """
- id: loyal_friend
  title: Друг пассажира
  description: Лояльность пассажира к концу сценария не ниже 90.
  rule: {type: scale_min, params: {scale: loyalty, min: 90}}
  rule_text: Завершите любой сценарий с лояльностью не ниже 90.
"""


def play(client, headers, moves):
    view = start(client, headers)
    for option_id in moves:
        response = choose(client, headers, view, option_id)
        assert response.status_code == 200, response.text
        view = response.json()
    return view


def play_expired_path(client, headers):
    view = start(client, headers)
    clock.travel(FIRST_TIMER_SECONDS + 1)
    view = expire(client, headers, view).json()
    for option_id in EXPIRED_PATH:
        response = choose(client, headers, view, option_id)
        assert response.status_code == 200, response.text
        view = response.json()
    return view


def debrief_of(client, headers, view):
    response = client.get(f"/api/runs/{view['run_id']}/debrief", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def earned_ids(client, headers):
    return {item["id"] for item in client.get("/api/achievements", headers=headers).json() if item["earned"]}


def test_achievement_awarded_by_rule(client, login):
    headers = login()
    first = debrief_of(client, headers, play_expired_path(client, headers))
    # истёкший таймер и неполная цепочка: из правил справочника выполняется только «первый рейс»
    assert [item["id"] for item in first["achievements_new"]] == ["first_run"]
    assert earned_ids(client, headers) == {"first_run"}
    second = debrief_of(client, headers, play_best_path(client, headers))
    new_ids = {item["id"] for item in second["achievements_new"]}
    assert new_ids == BEST_PATH_ACHIEVEMENTS - {"first_run"}
    assert earned_ids(client, headers) == BEST_PATH_ACHIEVEMENTS
    catalog = {item["id"]: item for item in client.get("/api/achievements", headers=headers).json()}
    assert catalog["four_steps"]["rule_type"] == "role_chain" and catalog["four_steps"]["earned_at"]
    assert catalog["no_incidents_5"]["earned"] is False and catalog["no_incidents_5"]["earned_at"] is None
    assert all(item["rule_text"] for item in catalog.values())


def test_achievement_once(client, login, app):
    headers = login()
    play_best_path(client, headers)
    again = debrief_of(client, headers, play_best_path(client, headers))
    assert again["achievements_new"] == [] and again["is_repeat"] is True
    with app.state.session_factory() as db:
        rows = db.scalars(select(AchievementEarned)).all()
        alerts = db.scalars(select(Notification).where(Notification.kind == "achievement")).all()
    assert len(rows) == len(BEST_PATH_ACHIEVEMENTS) and len(alerts) == len(BEST_PATH_ACHIEVEMENTS)


def test_notification_on_achievement(client, login):
    headers = login()
    view = play_best_path(client, headers)
    listed = client.get("/api/notifications", headers=headers).json()
    alerts = [item for item in listed if item["kind"] == "achievement"]
    assert {item["payload"]["achievement_id"] for item in alerts} == BEST_PATH_ACHIEVEMENTS
    assert all(item["payload"]["run_id"] == view["run_id"] and item["read_at"] is None for item in alerts)
    four_steps = next(item for item in alerts if item["payload"]["achievement_id"] == "four_steps")
    assert four_steps["title"] == "Достижение: Четыре шага" and four_steps["body"]
    read = client.post(f"/api/notifications/{four_steps['id']}/read", headers=headers)
    assert read.status_code == 200 and read.json()["read_at"]
    assert client.post("/api/notifications/read-all", headers=headers).json() == {"read": len(listed) - 1}
    assert all(item["read_at"] for item in client.get("/api/notifications", headers=headers).json())
    assert client.post("/api/notifications/read-all", headers=headers).json() == {"read": 0}
    foreign = client.post(f"/api/notifications/{four_steps['id']}/read", headers=login("VSM-1002"))
    assert error_code(foreign, 404) == "notification_not_found"


def test_xp_and_level_after_run(client, login):
    headers = login()
    before = client.get("/api/profile", headers=headers).json()
    assert before["xp_total"] == 0 and before["level"]["id"] == "trainee" and before["runs_count"] == 0
    assert before["last_run"] is None and before["rank_brigade"] == 1
    view = play_best_path(client, headers)
    profile = client.get("/api/profile", headers=headers).json()
    assert profile["xp_total"] == view["xp"] == 185
    assert profile["level"]["id"] == "conductor" and profile["xp_to_next"] == 400 - 185
    assert profile["runs_count"] == 1 and profile["last_run"]["run_id"] == view["run_id"]
    assert profile["achievements_count"] == len(BEST_PATH_ACHIEVEMENTS)
    assert profile["achievements_total"] == 10
    assert profile["bonus"] == {"active_total": 0, "expiring": []}
    debrief = debrief_of(client, headers, view)
    assert debrief["xp_breakdown"] == {"base": 100, "scales": 50, "tempo": 15, "role": 20}
    assert (debrief["level_before"]["id"], debrief["level_after"]["id"]) == ("trainee", "conductor")
    listed = client.get("/api/notifications", headers=headers).json()
    level_up = [item for item in listed if item["kind"] == "level_up"]
    assert len(level_up) == 1 and level_up[0]["payload"] == {"level_id": "conductor", "xp_total": 185}
    assert level_up[0]["title"] == "Новый уровень: Проводник"
    # наставник не участвует в рейтинге бригады, проводник с нулём очков стоит ниже
    assert client.get("/api/profile", headers=login("VSM-2001")).json()["rank_brigade"] is None
    assert client.get("/api/profile", headers=login("VSM-1002")).json()["rank_brigade"] == 2


def test_debrief_has_refs_and_better(client, login):
    headers = login()
    debrief = debrief_of(client, headers, play_expired_path(client, headers))
    assert debrief["outcome"] == "acceptable" and debrief["expired_timers"] == 1
    assert (debrief["loyalty_start"], debrief["safety_start"]) == (60, 70)
    steps = debrief["steps"]
    assert [step["step_no"] for step in steps] == [1, 2, 3, 4, 5, 6]
    expired = steps[0]
    assert expired["expired"] is True and expired["verdict"] == "expired" and expired["option_id"] is None
    assert expired["timer_seconds"] == FIRST_TIMER_SECONDS and expired["better"].startswith("Сразу сказать")
    assert [ref["key"] for ref in expired["refs"]] == ["sit_19", "sto_011_10_4"]
    assert expired["refs"][1]["quote"] and expired["refs"][1]["reconstructed"] is True
    assert expired["refs"][0]["number"] == 19 and expired["refs"][0]["phrase"].startswith("«Я рядом")
    assert expired["best_option"]["id"] == "call_chief_stay"
    assert expired["safety_after"] < expired["safety_before"]
    best = steps[1]
    assert best["option_id"] == "check_and_radio_chief" and best["verdict"] == "best"
    assert best["better"] is None and best["best_option"] is None and best["escalation_target"] == "chief"
    assert best["option_text"].startswith("Проверяю") and best["why"]
    assert all(step["refs"] for step in steps) and all(step["why"] for step in steps)
    assert debrief["ending"]["id"] == "ending_station_medics" and debrief["ending"]["summary"]
    assert [ref["key"] for ref in debrief["ending"]["refs"]] == ["sit_19", "sit_28", "sto_011_10_4"]
    assert debrief["role_chain"] == {"steps": [], "next_expected": "acknowledge", "complete": False}
    assert debrief["is_repeat"] is False and debrief["xp"] == debrief["score"]


def test_debrief_shows_delayed_and_competency_delta(client, login):
    headers = login()
    # уход за начальником поезда обещает вернуться, water_and_calm возвращает: штраф отменён
    moves = ["run_for_chief", "water_and_calm", "pa_medic", "brief_medic", "announce_calm"]
    view = play(client, headers, moves)
    debrief = debrief_of(client, headers, view)
    applied = [item for step in debrief["steps"] for item in step["delayed_applied"]]
    assert applied == [
        {
            "text": "Пассажир остался без персонала и испугался ещё сильнее.",
            "effects": {"loyalty": -10},
            "cancelled": True,
        }
    ]
    delta = {item["code"]: item for item in debrief["competencies_delta"]}
    # заработано medical: water_and_calm 1, pa_medic 2, brief_medic 1 из оценённых 8
    assert delta["medical"]["mastery_before"] is None
    assert delta["medical"]["mastery_after"] == pytest.approx(4 / 8)
    assert delta["medical"]["status"] == "few_data"
    assert delta["medical"]["title"] == "Первая помощь и здоровье"
    assert debrief["steps"][3]["best_option"]["id"] == "brief_medic_full"


def test_debrief_of_unfinished_run_rejected(client, login):
    headers = login()
    view = start(client, headers)
    unfinished = client.get(f"/api/runs/{view['run_id']}/debrief", headers=headers)
    assert error_code(unfinished, 409) == "run_not_finished"
    other = login("VSM-1002")
    assert error_code(client.get(f"/api/runs/{view['run_id']}/debrief", headers=other), 403) == "foreign_run"
    assert error_code(client.get("/api/runs/999999/debrief", headers=headers), 404) == "run_not_found"


def test_finish_twice_no_double_xp(client, login, app):
    headers = login()
    view = play_best_path(client, headers)
    assert error_code(choose(client, headers, view, "announce_calm"), 409) == "already_finished"
    assert error_code(expire(client, headers, view), 409) == "already_finished"
    stale = {"option_id": "announce_calm", "step_no": view["step_no"] - 1}
    late = client.post(f"/api/sessions/{view['run_id']}/choose", json=stale, headers=headers)
    assert error_code(late, 409) == "already_finished"
    with app.state.session_factory() as db:
        assert db.get(Profile, db.get(ScenarioRun, view["run_id"]).employee_id).xp_total == view["xp"]
        assert len(db.scalars(select(AchievementEarned)).all()) == len(BEST_PATH_ACHIEVEMENTS)
        completed = select(OutboxEvent).where(OutboxEvent.event_type == "run_completed")
        assert len(db.scalars(completed).all()) == 1


def test_outbox_run_completed(client, login, app):
    headers = login()
    view = play_best_path(client, headers)
    with app.state.session_factory() as db:
        events = db.scalars(select(OutboxEvent).order_by(OutboxEvent.id)).all()
    kinds = [event.event_type for event in events]
    assert kinds[0] == "run_completed" and kinds.count("achievement_earned") == len(BEST_PATH_ACHIEVEMENTS)
    assert kinds.count("level_up") == 1 and all(event.delivered_at is None for event in events)
    payload = events[0].payload_json
    assert payload["run_id"] == view["run_id"] and payload["employee_code"] == "VSM-1001"
    assert payload["outcome"] == "exemplary" and payload["xp"] == 185 and payload["role_complete"] is True
    assert payload["competencies"]["medical"] == {"earned": 7, "assessed": 8} and payload["finished_at"]


def test_outbox_cursor_and_ack(client, login, app):
    headers = login()
    play_best_path(client, headers)
    with app.state.session_factory() as db:
        first = outbox.fetch(db, 0, 2)
        assert [item["id"] for item in first["items"]] == [1, 2] and first["next_after_id"] == 2
        rest = outbox.fetch(db, first["next_after_id"], 50)
        assert rest["items"][0]["id"] == 3 and rest["next_after_id"] == rest["items"][-1]["id"]
        empty = outbox.fetch(db, rest["next_after_id"], 50)
        assert empty == {"items": [], "next_after_id": rest["next_after_id"]}
        assert outbox.ack(db, [1, 2], clock.now()) == 2
        assert outbox.ack(db, [1, 2, 999], clock.now()) == 0
        again = outbox.fetch(db, 0, 3)
    assert [bool(item["delivered_at"]) for item in again["items"]] == [True, True, False]
    assert again["items"][0]["event_type"] == "run_completed" and again["items"][0]["created_at"]


def test_notification_dedupe(client, app):
    now = clock.now()
    with app.state.session_factory() as db:
        employee_id = db.scalar(select(Profile.employee_id).order_by(Profile.employee_id))
        key = "achievement:test:1"
        args = (db, employee_id, "achievement", "Достижение: тест", "тело", {"a": 1}, key, now)
        assert notifications.create(*args) is not None
        assert notifications.create(*args) is None
        db.commit()
        rows = db.scalars(select(Notification)).all()
        assert len(rows) == 1 and rows[0].payload_json == {"a": 1}
        assert notifications.list_for(db, employee_id, 10)[0]["title"] == "Достижение: тест"


def test_competencies_updated(client, login, app):
    headers = login()
    play_best_path(client, headers)
    with app.state.session_factory() as db:
        rows = {row.competency: row for row in db.scalars(select(EmployeeCompetency)).all()}
    medical = rows["medical"]
    assert (medical.earned_sum, medical.assessed_sum, medical.runs_assessed) == (7, 8, 1)
    assert rows["medical"].mastery == pytest.approx(7 / 8) and rows["medical"].status == "few_data"
    assert rows["inclusion"].status == "gap" and rows["inclusion"].mastery is None
    profile = client.get("/api/profile", headers=headers).json()
    by_code = {item["code"]: item for item in profile["competencies"]}
    assert [item["code"] for item in profile["competencies"]][:2] == ["empathy", "rules"]
    assert by_code["medical"]["mastery"] == pytest.approx(7 / 8) and by_code["medical"]["title"]
    assert by_code["inclusion"] == {
        "code": "inclusion",
        "title": "Инклюзивность",
        "mastery": None,
        "status": "gap",
        "earned": 0,
        "assessed": 0,
        "runs_assessed": 0,
    }


def test_concurrent_finish_awards_once(app, settings):
    # две вкладки жмут последний вариант одновременно: один ход проходит, второй получает 409
    with TestClient(app) as first, TestClient(app) as second:
        body = {"employee_code": "VSM-1001", "pin": settings.demo_pin}
        headers = {"Authorization": f"Bearer {first.post('/api/auth/login', json=body).json()['token']}"}
        view = play(first, headers, BEST_PATH[:-1])
        barrier = threading.Barrier(2)

        def press(client):
            barrier.wait()
            return choose(client, headers, view, BEST_PATH[-1])

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(press, [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["error"]["code"] in ("stale_step", "already_finished")
    with app.state.session_factory() as db:
        run = db.get(ScenarioRun, view["run_id"])
        assert run.status == "finished" and db.get(Profile, run.employee_id).xp_total == run.xp_earned == 185
        assert len(db.scalars(select(AchievementEarned)).all()) == len(BEST_PATH_ACHIEVEMENTS)
        completed = select(OutboxEvent).where(OutboxEvent.event_type == "run_completed")
        assert len(db.scalars(completed).all()) == 1
        assert len(db.scalars(select(Notification).where(Notification.kind == "level_up")).all()) == 1


def test_profile_runs_history(client, login):
    headers = login()
    abandoned = start(client, headers)
    finished = play_best_path(client, headers)
    history = client.get("/api/profile/runs", headers=headers).json()
    assert [item["run_id"] for item in history] == [finished["run_id"], abandoned["run_id"]]
    assert history[0]["status"] == "finished" and history[0]["outcome"] == "exemplary"
    assert history[0]["xp"] == 185 and history[0]["loyalty_final"] == finished["loyalty"]
    assert history[0]["title"] == "Давит в груди" and history[0]["finished_at"]
    assert history[1]["status"] == "abandoned" and history[1]["xp"] is None


def test_achievements_yaml_is_checked(tmp_path):
    shutil.copytree(CONTENT_DIR, tmp_path / "content")
    path = tmp_path / "content" / "achievements.yaml"
    text = path.read_text(encoding="utf-8")
    assert achievements.check_achievements(load_content(tmp_path / "content")) == []
    broken = text.replace("type: role_chain, params: {times: 1}", "type: role_chain, params: {}")
    broken = broken.replace("type: first_run", "type: first_flight")
    broken = broken.replace("competency: inclusion", "competency: kindness")
    path.write_text(broken, encoding="utf-8")
    problems = achievements.check_achievements(load_content(tmp_path / "content"))
    assert problems == [
        "first_run: rule.type должен быть одним из " + ", ".join(achievements.RULES),
        "four_steps: в params нет times",
        "inclusion_master: компетенции «kindness» нет в competencies.yaml",
    ]
    path.write_text("- id: only\n", encoding="utf-8")
    assert achievements.check_achievements(load_content(tmp_path / "content")) == [
        "запись 1: нужны поля id, title, description, rule, rule_text"
    ]


def bump_mtime(path):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5 * 10**9))


def test_new_achievement_appears_without_restart(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        body = {"employee_code": "VSM-1001", "pin": settings.demo_pin}
        headers = {"Authorization": f"Bearer {client.post('/api/auth/login', json=body).json()['token']}"}
        ids = [item["id"] for item in client.get("/api/achievements", headers=headers).json()]
        assert "loyal_friend" not in ids
        path = content_dir / "achievements.yaml"
        path.write_text(path.read_text(encoding="utf-8") + NEW_ACHIEVEMENT, encoding="utf-8")
        bump_mtime(path)
        catalog = client.get("/api/achievements", headers=headers).json()
        added = next(item for item in catalog if item["id"] == "loyal_friend")
        assert added["earned"] is False and added["rule_type"] == "scale_min"
        # сломанная запись не роняет сервер: до исправления живёт прежний справочник
        text = path.read_text(encoding="utf-8")
        broken = text.replace("type: scale_min, params: {scale: loyalty", "type: magic, params: {")
        path.write_text(broken, encoding="utf-8")
        bump_mtime(path)
        assert client.get("/api/health").json()["content_errors"] == 1
        assert len(client.get("/api/achievements", headers=headers).json()) == len(catalog)
        path.write_text(text, encoding="utf-8")
        bump_mtime(path)
        view = play(client, headers, BEST_PATH)
        assert view["loyalty"] >= 90
        debrief = client.get(f"/api/runs/{view['run_id']}/debrief", headers=headers).json()
        assert "loyal_friend" in [item["id"] for item in debrief["achievements_new"]]
