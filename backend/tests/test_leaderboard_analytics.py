"""Лидерборд по трём охватам, челленджи с бонусами и сгорающими баллами, уведомления о сгорании
при чтении и аналитика компетенций: всё считается из прохождений, ничего не хранится снимком."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app import clock
from app.models import BonusPoint, Employee, Notification, OutboxEvent
from app.scenarios.loader import load_content
from app.services import challenges
from tests.test_api_progress import debrief_of, play
from tests.test_api_sessions import BEST_PATH, error_code, play_best_path, start

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
WHEELCHAIR_BEST = [
    "greet_ask_preference",
    "operate_lift_by_rules",
    "seat_and_fold_wheelchair",
    "help_place_luggage",
    "inform_chief_destination_assist",
    "offer_meal_to_seat",
]


def board(client, headers, scope="brigade", **params):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    response = client.get(f"/api/leaderboard?scope={scope}" + (f"&{query}" if query else ""), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def add_bonus(app, employee_code, points, expires_at, reason="Бонус за прошлый челлендж"):
    with app.state.session_factory() as db:
        employee = db.scalar(select(Employee).where(Employee.code == employee_code))
        row = BonusPoint(
            employee_id=employee.id,
            points=points,
            reason=reason,
            challenge_id=None,
            earned_at=clock.now(),
            expires_at=expires_at,
        )
        db.add(row)
        db.commit()
        return row.id


def test_leaderboard_changes_after_attempt(client, login):
    first = login("VSM-1001")
    second = login("VSM-1002")
    before = board(client, first)
    assert before["scope"] == "brigade" and before["scope_title"] == "Бригада М-01"
    assert [row["employee_code"] for row in before["rows"][:2]] == ["VSM-1001", "VSM-1002"]
    assert before["me"]["rank"] == 1 and before["me"]["score"] == 0 and before["me"]["is_me"] is True
    view = play_best_path(client, second)
    after = board(client, first)
    top = after["rows"][0]
    assert top["employee_code"] == "VSM-1002" and top["score"] == view["xp"] == 185
    assert top["best_scores_sum"] == 185 and top["bonus_points"] == 0 and top["achievements"] == 4
    assert after["me"]["rank"] == 2 and after["me"]["employee_code"] == "VSM-1001"
    assert client.get("/api/profile", headers=first).json()["rank_brigade"] == 2
    assert board(client, second)["me"]["rank"] == 1
    # повтор сценария с меньшим счётом не портит рейтинг: берётся лучший результат по сценарию
    play(
        client,
        second,
        ["run_for_chief", "rule_without_acknowledge", "pa_medic", "brief_medic", "announce_calm"],
    )
    assert board(client, second)["me"]["best_scores_sum"] == 185


def test_leaderboard_scopes(client, login):
    headers = login("VSM-1001")
    brigade = board(client, headers, "brigade")
    depot = board(client, headers, "depot")
    company = board(client, headers, "company")
    codes = lambda payload: {row["employee_code"] for row in payload["rows"]}  # noqa: E731
    assert codes(brigade) <= codes(depot) <= codes(company)
    assert depot["scope_title"] == "ТЧ Москва-ВСМ" and company["scope_title"] == "Компания"
    assert all(row["brigade"] == "М-01" for row in brigade["rows"])
    assert all(row["depot"] == "ТЧ Москва-ВСМ" for row in depot["rows"])
    assert "VSM-2001" not in codes(company)
    assert [row["rank"] for row in company["rows"]] == list(range(1, len(company["rows"]) + 1))
    short = board(client, headers, "company", limit=1)
    assert len(short["rows"]) == 1 and short["me"]["employee_code"] == "VSM-1001"
    mentor = board(client, login("VSM-2001"))
    assert mentor["me"] is None and mentor["rows"]
    assert error_code(client.get("/api/leaderboard?scope=planet", headers=headers), 422) == "validation_error"
    assert error_code(client.get("/api/leaderboard?limit=0", headers=headers), 422) == "validation_error"


def test_expired_bonus_not_counted(client, login, app):
    headers = login("VSM-1001")
    now = clock.now()
    add_bonus(app, "VSM-1001", 40, now + timedelta(hours=1))
    add_bonus(app, "VSM-1001", 25, None, reason="Бессрочный бонус наставника")
    add_bonus(app, "VSM-1001", 90, now - timedelta(minutes=1), reason="Уже сгорел")
    me = board(client, headers)["me"]
    assert (me["score"], me["best_scores_sum"], me["bonus_points"]) == (65, 0, 65)
    assert client.get("/api/profile", headers=headers).json()["bonus"]["active_total"] == 65
    clock.travel(2 * 3600)
    me = board(client, headers)["me"]
    assert (me["score"], me["bonus_points"]) == (25, 25)
    assert client.get("/api/profile", headers=headers).json()["bonus"]["active_total"] == 25


def test_notification_on_expiring_points(client, login, app):
    headers = login("VSM-1001")
    now = clock.now()
    bonus_id = add_bonus(app, "VSM-1001", 30, now + timedelta(hours=36), reason="Челлендж «Четыре шага»")
    add_bonus(app, "VSM-1001", 50, now + timedelta(days=5), reason="Челлендж «Неделя безопасности»")
    listed = client.get("/api/notifications", headers=headers).json()
    expiring = [item for item in listed if item["kind"] == "points_expiring"]
    assert len(expiring) == 1
    alert = expiring[0]
    assert alert["title"] == "Сгорают 30 баллов" and alert["read_at"] is None
    assert alert["body"] == "Через 36 часов сгорают 30 баллов к рейтингу: Челлендж «Четыре шага»."
    assert alert["payload"] == {
        "bonus_id": bonus_id,
        "points": 30,
        "expires_at": clock.iso(now + timedelta(hours=36)),
    }
    # повторное чтение, профиль и челленджи не дублируют уведомление
    client.get("/api/notifications", headers=headers)
    client.get("/api/profile", headers=headers)
    client.get("/api/challenges", headers=headers)
    listed = client.get("/api/notifications", headers=headers).json()
    assert sum(item["kind"] == "points_expiring" for item in listed) == 1
    profile = client.get("/api/profile", headers=headers).json()
    assert profile["bonus"]["active_total"] == 80
    assert [item["points"] for item in profile["bonus"]["expiring"]] == [30]
    # через трое суток в окно предупреждения входит второй бонус, первый уже сгорел
    clock.travel(3 * 24 * 3600)
    headers = login("VSM-1001")
    listed = client.get("/api/notifications", headers=headers).json()
    expiring = [item for item in listed if item["kind"] == "points_expiring"]
    assert [item["payload"]["points"] for item in expiring] == [50, 30]
    assert expiring[0]["body"].startswith("Через 48 часов сгорают 50 баллов")
    assert client.get("/api/profile", headers=headers).json()["bonus"]["active_total"] == 50


def test_notify_expiring_skips_past(client, login, app):
    headers = login("VSM-1001")
    add_bonus(app, "VSM-1001", 20, clock.now() - timedelta(hours=1), reason="Сгорел до первого чтения")
    listed = client.get("/api/notifications", headers=headers).json()
    assert not [item for item in listed if item["kind"] == "points_expiring"]
    with app.state.session_factory() as db:
        assert db.scalar(select(Notification).where(Notification.kind == "points_expiring")) is None


def test_challenges_listed_and_announced(client, login):
    headers = login("VSM-1001")
    listed = client.get("/api/challenges", headers=headers).json()
    assert [item["id"] for item in listed] == ["safety_week", "four_steps_week", "inclusion_week"]
    safety = listed[0]
    assert safety["title"] == "Неделя безопасности" and safety["status"] == "active"
    assert safety["scenario_ids"] == ["medical_chest_pain", "smoking_vestibule", "unattended_bag"]
    assert safety["progress"] == {"done": 0, "total": 3, "completed": False}
    assert safety["bonus_points"] == 50 and safety["bonus_expires_at"] is None
    # окно открыто сидом, а не этим запросом: проверяем длину окна, а не его границы
    window = datetime.fromisoformat(safety["ends_at"]) - datetime.fromisoformat(safety["starts_at"])
    assert window == timedelta(days=7)
    assert listed[1]["progress"]["total"] == 3 and listed[2]["progress"]["total"] == 1
    alerts = [
        item
        for item in client.get("/api/notifications", headers=headers).json()
        if item["kind"] == "challenge"
    ]
    assert {item["payload"]["challenge_id"] for item in alerts} == {
        "safety_week",
        "four_steps_week",
        "inclusion_week",
    }
    assert any(item["title"].startswith("Челлендж «Неделя безопасности» до ") for item in alerts)
    assert all(item["payload"]["ends_at"] and item["read_at"] is None for item in alerts)
    # у наставника те же объявления, свой прогресс
    mentor = client.get("/api/challenges", headers=login("VSM-2001")).json()
    assert [item["status"] for item in mentor] == ["active", "active", "active"]


def test_challenge_progress_and_bonus(client, login, app):
    headers = login("VSM-1001")
    started = clock.now()
    play_best_path(client, headers)
    by_id = {item["id"]: item for item in client.get("/api/challenges", headers=headers).json()}
    assert by_id["safety_week"]["progress"] == {"done": 1, "total": 3, "completed": False}
    assert by_id["four_steps_week"]["progress"] == {"done": 1, "total": 3, "completed": False}
    play_best_path(client, headers)
    assert by_id["safety_week"]["progress"]["done"] == 1
    # тот же сценарий в третий раз: для «Четырёх шагов» считаются прохождения, а не разные сценарии
    clock.freeze(clock.now())
    view = play_best_path(client, headers)
    debrief = debrief_of(client, headers, view)
    assert debrief["challenges_completed"] == [
        {
            "id": "four_steps_week",
            "title": "Четыре шага",
            "bonus_points": 30,
            "bonus_expires_at": clock.iso(clock.now() + timedelta(hours=168)),
        }
    ]
    by_id = {item["id"]: item for item in client.get("/api/challenges", headers=headers).json()}
    done = by_id["four_steps_week"]
    assert done["status"] == "completed" and done["progress"] == {"done": 3, "total": 3, "completed": True}
    assert done["bonus_expires_at"] == debrief["challenges_completed"][0]["bonus_expires_at"]
    me = board(client, headers)["me"]
    assert (me["bonus_points"], me["best_scores_sum"], me["score"]) == (30, 185, 215)
    alerts = [
        item
        for item in client.get("/api/notifications", headers=headers).json()
        if item["kind"] == "challenge"
    ]
    done_alert = next(
        item
        for item in alerts
        if item["payload"].get("bonus_points") == 30 and "expires_at" in item["payload"]
    )
    assert done_alert["title"] == "Челлендж выполнен: Четыре шага"
    with app.state.session_factory() as db:
        events = db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "challenge_completed")).all()
        assert len(events) == 1 and events[0].payload_json["challenge_id"] == "four_steps_week"
        assert events[0].payload_json["run_id"] == view["run_id"]
        bonuses = db.scalars(select(BonusPoint)).all()
        assert (
            len(bonuses) == 1
            and bonuses[0].run_id == view["run_id"]
            and bonuses[0].challenge_id == "four_steps_week"
        )
    # четвёртое прохождение бонус не удваивает
    again = debrief_of(client, headers, play_best_path(client, headers))
    assert again["challenges_completed"] == []
    assert board(client, headers)["me"]["bonus_points"] == 30
    # после окна челлендж истекает для тех, кто не успел, а бонус выполнившего сгорает через неделю
    clock.travel(8 * 24 * 3600)
    assert clock.now() > started + timedelta(days=7)
    other = login("VSM-1002")
    statuses = {item["id"]: item["status"] for item in client.get("/api/challenges", headers=other).json()}
    assert statuses == {"safety_week": "expired", "four_steps_week": "expired", "inclusion_week": "active"}
    assert board(client, login("VSM-1001"))["me"]["bonus_points"] == 0


def test_run_after_window_does_not_count(client, login):
    clock.travel(15 * 24 * 3600)
    headers = login("VSM-1001")
    play(client, headers, BEST_PATH)
    by_id = {item["id"]: item for item in client.get("/api/challenges", headers=headers).json()}
    assert by_id["safety_week"]["progress"]["done"] == 0 and by_id["safety_week"]["status"] == "expired"
    assert by_id["four_steps_week"]["progress"]["done"] == 0


def test_inclusion_challenge_requires_exemplary(client, login):
    headers = login("VSM-1001")
    view = start(client, headers, "wheelchair_boarding")
    for option_id in WHEELCHAIR_BEST:
        response = client.post(
            f"/api/sessions/{view['run_id']}/choose",
            json={"option_id": option_id, "step_no": view["step_no"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        view = response.json()
    assert view["status"] == "finished" and view["outcome"] == "exemplary"
    debrief = debrief_of(client, headers, view)
    assert [item["id"] for item in debrief["challenges_completed"]] == ["inclusion_week"]
    by_id = {item["id"]: item for item in client.get("/api/challenges", headers=headers).json()}
    assert (
        by_id["inclusion_week"]["status"] == "completed" and by_id["inclusion_week"]["progress"]["done"] == 1
    )


def test_challenges_yaml_is_checked(tmp_path):
    shutil.copytree(CONTENT_DIR, tmp_path / "content")
    path = tmp_path / "content" / "challenges.yaml"
    text = path.read_text(encoding="utf-8")
    assert challenges.check_challenges(load_content(tmp_path / "content")) == []
    broken = text.replace("type: no_incident_all, params: {}", "type: no_accidents, params: {}")
    broken = broken.replace("params: {count: 3}", "params: {count: 'три', extra: 1}")
    broken = broken.replace("params: {outcome: exemplary}", "params: {outcome: perfect}")
    broken = broken.replace("bonus_points: 40", "bonus_points: 0")
    broken = broken.replace("scenario_ids: [wheelchair_boarding]", "scenario_ids: []")
    path.write_text(broken, encoding="utf-8")
    assert challenges.check_challenges(load_content(tmp_path / "content")) == [
        "safety_week: condition.type должен быть одним из no_incident_all, role_chain_count, outcome_min",
        "four_steps_week: параметр count должен быть целым числом больше нуля",
        "four_steps_week: в condition.params лишний ключ extra",
        "inclusion_week: bonus_points должно быть целым числом больше нуля",
        "inclusion_week: исход должен быть одним из incident, acceptable, exemplary",
        "inclusion_week: условию outcome_min нужен непустой scenario_ids",
    ]
    path.write_text("- id: only\n", encoding="utf-8")
    assert challenges.check_challenges(load_content(tmp_path / "content")) == [
        "запись 1: нужны непустые строки id, title, description"
    ]
