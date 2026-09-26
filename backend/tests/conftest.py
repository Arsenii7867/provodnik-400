"""Общие фикстуры: настройки с отдельной файловой SQLite на каждый тест, приложение, TestClient
и вход демо-аккаунтом. Время в тестах подменяется только через app.clock, моков нет; часы и
счётчик попыток входа сбрасываются перед каждым тестом."""

import os

import pytest
from fastapi.testclient import TestClient

from app import clock, ratelimit
from app.config import load_settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    os.environ["DATABASE_URL"] = "sqlite:///" + (tmp_path / "test.db").as_posix()
    os.environ["APP_ENV"] = "test"
    # папки dist здесь нет: тесты API не зависят от собранного фронта
    os.environ["FRONTEND_DIST"] = (tmp_path / "dist").as_posix()
    return load_settings()


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture(autouse=True)
def fresh_clock_and_limits():
    clock.reset()
    ratelimit.reset()
    yield
    clock.reset()
    ratelimit.reset()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def login(client, settings):
    def do_login(employee_code="VSM-1001"):
        body = {"employee_code": employee_code, "pin": settings.demo_pin}
        response = client.post("/api/auth/login", json=body)
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    return do_login
