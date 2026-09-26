"""Живое изменение развилки: текстовая правка YAML добавляет вариант, валидатор его принимает,
движок проходит новую ветку, а работающий сервер видит вариант без перезапуска."""

import dataclasses
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app import clock
from app.main import create_app
from app.scenarios import engine, validator

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SCENARIO = "medical_chest_pain"
NEW_OPTION = """\
      - id: ask_neighbor_press_call
        text: Прошу соседку нажать кнопку вызова, сам остаюсь рядом и говорю «Я рядом, помощь уже идёт».
        role_step: acknowledge
        effects: {loyalty: 5, safety: 5}
        competencies: {empathy: 1}
        next: at_the_seat
        debrief:
          verdict: ok
          why: Пассажир не остаётся один, но начальник поезда вызван не напрямую и позже, чем мог бы.
          better: Вызвать начальника поезда по радиосвязи самому, не отходя от пассажира.
          refs: [sit_19]
"""


def bump_mtime(path):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5 * 10**9))


def add_option(path):
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.rstrip() == "    options:")
    lines[index + 1 : index + 1] = [NEW_OPTION]
    path.write_text("".join(lines), encoding="utf-8")
    bump_mtime(path)


def test_timer_change_keeps_recorded_deadline(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        body = {"employee_code": "VSM-1001", "pin": settings.demo_pin}
        token = client.post("/api/auth/login", json=body).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        view = client.post("/api/sessions", json={"scenario_id": SCENARIO}, headers=headers).json()
        assert view["node"]["timer_seconds"] == 20

        path = content_dir / "scenarios" / f"{SCENARIO}.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("seconds: 20", "seconds: 60", 1), encoding="utf-8"
        )
        bump_mtime(path)
        clock.travel(25)
        # дедлайн записан при входе в узел: новый таймер из файла действует только для следующих прохождений
        same = client.get(f"/api/sessions/{view['run_id']}", headers=headers).json()
        assert same["node"]["timer_seconds"] == 20 and same["deadline_at"] == view["deadline_at"]
        assert client.get("/api/health").json()["content_errors"] == 0
        late = client.post(
            f"/api/sessions/{view['run_id']}/choose",
            json={"option_id": "call_chief_stay", "step_no": 0},
            headers=headers,
        )
        assert late.status_code == 200 and late.json()["expired"] is True
        fresh = client.post("/api/sessions", json={"scenario_id": SCENARIO}, headers=headers).json()
        assert fresh["node"]["timer_seconds"] == 60


def test_live_change_adds_branch(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        body = {"employee_code": "VSM-1001", "pin": settings.demo_pin}
        token = client.post("/api/auth/login", json=body).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        view = client.post("/api/sessions", json={"scenario_id": SCENARIO}, headers=headers).json()
        assert "ask_neighbor_press_call" not in [option["id"] for option in view["node"]["options"]]

        add_option(content_dir / "scenarios" / f"{SCENARIO}.yaml")
        content, report = validator.load_validated(content_dir)
        assert report["errors"] == 0, report["summary"]
        scenario = content.scenarios[SCENARIO]
        now = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
        state = engine.start(scenario, content, now)
        state, step = engine.apply_choice(scenario, content, state, "ask_neighbor_press_call", now, 1.0)
        assert state["node"] == "at_the_seat"
        assert step["loyalty_after"] == step["loyalty_before"] + round(5 * 1.25)

        refreshed = client.get(f"/api/sessions/{view['run_id']}", headers=headers).json()
        assert "ask_neighbor_press_call" in [option["id"] for option in refreshed["node"]["options"]]
        moved = client.post(
            f"/api/sessions/{view['run_id']}/choose",
            json={"option_id": "ask_neighbor_press_call", "step_no": refreshed["step_no"]},
            headers=headers,
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["node"]["id"] == "at_the_seat"
        assert moved.json()["last_step"]["role_step"] == "acknowledge"
        assert client.get("/api/health").json()["content_errors"] == 0


def test_idempotent_start_survives_changed_default_class(settings, tmp_path):
    content_dir = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, content_dir)
    app = create_app(dataclasses.replace(settings, content_dir=content_dir))
    with TestClient(app) as client:
        credentials = {"employee_code": "VSM-1001", "pin": settings.demo_pin}
        token = client.post("/api/auth/login", json=credentials).json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "before-class-edit"}
        body = {"scenario_id": SCENARIO}
        first = client.post("/api/sessions", json=body, headers=headers)
        assert first.status_code == 201
        assert first.json()["context"]["service_class"] == "business"

        path = content_dir / "scenarios" / f"{SCENARIO}.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("service_class: business", "service_class: standard", 1),
            encoding="utf-8",
        )
        bump_mtime(path)
        assert app.state.store.scenario(SCENARIO)["context"]["service_class"] == "standard"
        replay = client.post("/api/sessions", json=body, headers=headers)
        assert replay.status_code == 200
        assert replay.json()["run_id"] == first.json()["run_id"]
        assert replay.json()["context"]["service_class"] == "business"
        conflict = client.post("/api/sessions", json=body | {"service_class": "standard"}, headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_mismatch"
