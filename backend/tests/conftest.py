"""Общие фикстуры: настройки с отдельной файловой SQLite на каждый тест, приложение, TestClient
и вход демо-аккаунтом. База с людьми готовится один раз на сессию и копируется каждому тесту:
38 хэшей PIN стоят около секунды, а история прохождений тестам API не нужна и создаётся только
там, где проверяется сам сид. Время в тестах подменяется только через app.clock, моков нет;
часы и счётчик попыток входа сбрасываются перед каждым тестом."""

import os
import shutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import clock, ratelimit
from app.config import load_settings
from app.db import make_engine, prepare_database
from app.main import create_app
from app.scenarios.store import ContentStore
from app.seed import seed


def use_database(path):
    os.environ["DATABASE_URL"] = "sqlite:///" + path.as_posix()
    os.environ["APP_ENV"] = "test"
    # папки dist здесь нет: тесты API не зависят от собранного фронта
    os.environ["FRONTEND_DIST"] = (path.parent / "dist").as_posix()
    return load_settings()


@pytest.fixture(scope="session")
def people_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("seed") / "template.db"
    settings = use_database(path)
    engine = make_engine(settings.database_url)
    prepare_database(engine)
    with sessionmaker(engine)() as db:
        seed(db, ContentStore(settings.content_dir), settings, clock.now(), history=False)
    engine.dispose()
    return path


@pytest.fixture
def settings(tmp_path, people_template):
    target = tmp_path / "test.db"
    shutil.copy(people_template, target)
    return use_database(target)


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
