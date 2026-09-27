"""Администрирование контента наставником: перечитывание с отчётом валидатора и уведомлениями
о новых сценариях, проверка файлов без применения, запрет для проводника."""

import dataclasses
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import ActionLog, Challenge, Employee, Notification
from tests.test_api_sessions import error_code

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SCENARIO = "medical_chest_pain"


def make_copy(content_dir, new_id):
    source = content_dir / "scenarios" / f"{SCENARIO}.yaml"
    copy = content_dir / "scenarios" / f"{new_id}.yaml"
    copy.write_text(
        source.read_text(encoding="utf-8").replace(f"id: {SCENARIO}", f"id: {new_id}", 1), encoding="utf-8"
    )
    return copy


def login_as(client, code, pin):
    response = client.post("/api/auth/login", json={"employee_code": code, "pin": pin})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_reload_mentor_only(client, login):
    conductor = login("VSM-1001")
    assert error_code(client.post("/api/admin/scenarios/reload", headers=conductor), 403) == "role_required"
    assert error_code(client.get("/api/admin/scenarios/validate", headers=conductor), 403) == "role_required"
    assert error_code(client.post("/api/admin/scenarios/reload"), 401) == "token_missing"
    mentor = login("VSM-2001")
    report = client.post("/api/admin/scenarios/reload", headers=mentor).json()
    assert SCENARIO in report["loaded"] and report["new"] == [] and report["removed"] == []
    assert (
        report["errors"] == []
        and report["summary"].startswith("ИТОГ: сценариев=")
        and report["notified"] == 0
    )
    assert client.get("/api/admin/scenarios/validate", headers=mentor).json()["loaded"] == report["loaded"]


@pytest.mark.parametrize("catalog_reads_first", [False, True])
def test_reload_creates_new_scenario_notifications(settings, tmp_path, catalog_reads_first):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        mentor = login_as(client, "VSM-2001", settings.demo_pin)
        conductor = login_as(client, "VSM-1001", settings.demo_pin)
        make_copy(content_dir, "medical_copy")
        if catalog_reads_first:
            listed = client.get("/api/scenarios", headers=conductor)
            assert listed.status_code == 200
            assert "medical_copy" in {item["id"] for item in listed.json()}
        report = client.post("/api/admin/scenarios/reload", headers=mentor).json()
        with app.state.session_factory() as db:
            employees = db.scalar(select(Employee.id).order_by(Employee.id.desc()))
            headcount = len(db.scalars(select(Employee.id)).all())
        assert employees and report["new"] == ["medical_copy"] and report["notified"] == headcount
        assert "medical_copy" in report["loaded"] and report["errors"] == []
        listed = client.get("/api/notifications", headers=conductor).json()
        fresh = [item for item in listed if item["kind"] == "new_scenario"]
        assert len(fresh) == 1 and fresh[0]["payload"] == {"scenario_id": "medical_copy"}
        assert fresh[0]["title"] == "Новый сценарий: Давит в груди" and fresh[0]["body"]
        # повторное перечитывание ничего нового не находит и уведомлений не дублирует
        again = client.post("/api/admin/scenarios/reload", headers=mentor).json()
        assert again["new"] == [] and again["notified"] == 0
        with app.state.session_factory() as db:
            rows = db.scalars(select(Notification).where(Notification.kind == "new_scenario")).all()
            assert len(rows) == headcount
            logged = db.scalars(select(ActionLog).where(ActionLog.action == "content_reloaded")).all()
            assert len(logged) == 2 and logged[0].payload_json["new"] == ["medical_copy"]
        ids = {item["id"] for item in client.get("/api/scenarios", headers=conductor).json()}
        assert "medical_copy" in ids


def test_validate_report(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        mentor = login_as(client, "VSM-2001", settings.demo_pin)
        clean = client.get("/api/admin/scenarios/validate", headers=mentor).json()
        assert clean["errors"] == [] and clean["new"] == [] and clean["removed"] == []
        broken = make_copy(content_dir, "broken_copy")
        text = broken.read_text(encoding="utf-8").replace("next: at_the_seat", "next: nowhere", 1)
        broken.write_text(text, encoding="utf-8")
        report = client.get("/api/admin/scenarios/validate", headers=mentor).json()
        assert report["new"] == [] and report["removed"] == [] and report["loaded"] == clean["loaded"]
        assert report["errors"] and report["errors"][0]["file"] == "broken_copy.yaml"
        assert report["errors"][0]["line"] > 0 and "nowhere" in report["errors"][0]["message"]
        assert report["summary"].startswith("ИТОГ: сценариев=") and "ошибок=0" not in report["summary"]
        # проверка ничего не применяет: сломанный файл в каталог не попал и не сломал его
        applied = client.post("/api/admin/scenarios/reload", headers=mentor).json()
        assert applied["errors"][0]["file"] == "broken_copy.yaml" and "broken_copy" not in applied["loaded"]
        assert client.get("/api/health").json()["content_errors"] == 1
        broken.unlink()
        assert client.post("/api/admin/scenarios/reload", headers=mentor).json()["errors"] == []
        assert client.get("/api/health").json()["content_errors"] == 0


def test_reload_activates_new_challenge(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        mentor = login_as(client, "VSM-2001", settings.demo_pin)
        path = content_dir / "challenges.yaml"
        extra = (
            "\n- id: medical_week\n  title: Неделя первой помощи\n"
            "  description: Образцово пройти сценарий с болью в груди за неделю.\n"
            "  scenario_ids: [medical_chest_pain]\n"
            "  condition: {type: outcome_min, params: {outcome: exemplary}}\n"
            "  bonus_points: 20\n  duration_days: 7\n"
        )
        path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
        report = client.post("/api/admin/scenarios/reload", headers=mentor).json()
        assert report["errors"] == []
        listed = client.get("/api/challenges", headers=mentor).json()
        assert [item["id"] for item in listed][-1] == "medical_week" and listed[-1]["status"] == "active"
        alerts = [
            item
            for item in client.get("/api/notifications", headers=mentor).json()
            if item["kind"] == "challenge"
        ]
        assert any(item["payload"]["challenge_id"] == "medical_week" for item in alerts)
        with app.state.session_factory() as db:
            assert db.get(Challenge, "medical_week").bonus_points == 20


def test_reload_rejects_duplicate_challenge_scenarios_and_recovers(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        mentor = login_as(client, "VSM-2001", settings.demo_pin)
        path = content_dir / "challenges.yaml"
        original = path.read_text(encoding="utf-8")
        extra = (
            "\n- id: duplicate_week\n  title: Неделя первой помощи\n"
            "  description: Образцово пройти сценарий с болью в груди.\n"
            "  scenario_ids: [medical_chest_pain, medical_chest_pain]\n"
            "  condition: {type: outcome_min, params: {outcome: exemplary}}\n"
            "  bonus_points: 20\n  duration_days: 7\n"
        )
        with app.state.session_factory() as db:
            notices_before = db.scalar(select(func.count()).select_from(Notification))
        path.write_text(original + extra, encoding="utf-8")
        report = client.post("/api/admin/scenarios/reload", headers=mentor).json()
        assert any("scenario_ids не должен содержать повторы" in item["message"] for item in report["errors"])
        assert "duplicate_week" not in {item["id"] for item in app.state.store.content().challenges}
        with app.state.session_factory() as db:
            assert db.get(Challenge, "duplicate_week") is None
            assert db.scalar(select(func.count()).select_from(Notification)) == notices_before

        # После удаления повтора тот же челлендж можно объявить обычной перезагрузкой контента.
        fixed = extra.replace("medical_chest_pain, medical_chest_pain", "medical_chest_pain")
        path.write_text(original + fixed, encoding="utf-8")
        assert client.post("/api/admin/scenarios/reload", headers=mentor).json()["errors"] == []
        with app.state.session_factory() as db:
            assert db.get(Challenge, "duplicate_week").scenario_ids_json == ["medical_chest_pain"]
            headcount = db.scalar(select(func.count()).select_from(Employee))
            assert db.scalar(select(func.count()).select_from(Notification)) == notices_before + headcount


def test_cold_start_rejects_duplicate_challenge_scenarios_and_recovers(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    path = content_dir / "challenges.yaml"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace("[wheelchair_boarding]", "[wheelchair_boarding, wheelchair_boarding]"),
        encoding="utf-8",
    )
    app = create_app(
        dataclasses.replace(
            settings, content_dir=content_dir, database_url=f"sqlite:///{tmp_path / 'cold-start.db'}"
        )
    )
    with TestClient(app) as client:
        assert any("scenario_ids не должен содержать повторы" in error for error in app.state.store.errors)
        with app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Challenge)) == 0
            assert (
                db.scalar(
                    select(func.count()).select_from(Notification).where(Notification.kind == "challenge")
                )
                == 0
            )

        path.write_text(original, encoding="utf-8")
        mentor = login_as(client, "VSM-2001", settings.demo_pin)
        assert client.post("/api/admin/scenarios/reload", headers=mentor).json()["errors"] == []
        with app.state.session_factory() as db:
            assert set(db.scalars(select(Challenge.id))) == {
                "safety_week",
                "four_steps_week",
                "inclusion_week",
            }
            assert db.get(Challenge, "inclusion_week").scenario_ids_json == ["wheelchair_boarding"]
            headcount = db.scalar(select(func.count()).select_from(Employee))
            assert (
                db.scalar(
                    select(func.count()).select_from(Notification).where(Notification.kind == "challenge")
                )
                == 3 * headcount
            )
