"""Общие фикстуры: настройки с временной файловой SQLite на всю сессию тестов, приложение
и TestClient. Время в тестах подменяется только через app.clock, моков нет."""

import os

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("data")
    os.environ["DATABASE_URL"] = "sqlite:///" + (data_dir / "test.db").as_posix()
    os.environ["APP_ENV"] = "test"
    # папки dist здесь нет: тесты API не зависят от собранного фронта
    os.environ["FRONTEND_DIST"] = (data_dir / "dist").as_posix()
    return load_settings()


@pytest.fixture(scope="session")
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client
