"""Собранный фронт раздаётся с порта сервера: ассеты файлами, маршруты React через index.html,
а неизвестные адреса API остаются ошибками в едином формате."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def spa_client(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Проводник 400</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    app = create_app(dataclasses.replace(settings, frontend_dist=dist))
    with TestClient(app) as client:
        yield client


def test_react_routes_serve_index(spa_client):
    for path in ("/", "/login", "/play/12"):
        response = spa_client.get(path)
        assert response.status_code == 200
        assert "Проводник 400" in response.text


def test_assets_served_as_files(spa_client):
    response = spa_client.get("/assets/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_unknown_api_path_is_not_index(spa_client):
    response = spa_client.get("/api/nothing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_missing_file_is_404(spa_client):
    response = spa_client.get("/favicon.png")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_without_dist_root_is_404(client):
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
