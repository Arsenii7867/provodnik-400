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
    (dist / "index.html").write_text(
        "<!doctype html><title>Проводник 400</title>"
        '<script type="module" src="/assets/app.js?v=1"></script>'
        '<link rel="stylesheet" href="/assets/app.css">',
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("body { color: black; }", encoding="utf-8")
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


def test_readiness_accepts_complete_application(spa_client):
    response = spa_client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {"database": True, "content": True, "frontend": True}


def test_readiness_rejects_frontend_built_after_app_creation(client, settings):
    dist = settings.frontend_dist
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Late build</title>", encoding="utf-8")

    assert client.get("/").status_code == 404
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["frontend"] is False


@pytest.mark.parametrize("asset", ("app.js", "app.css"))
def test_readiness_rejects_missing_referenced_asset(spa_client, asset):
    dist = spa_client.app.state.settings.frontend_dist
    (dist / "assets" / asset).unlink()

    assert spa_client.get("/").status_code == 200
    assert spa_client.get(f"/assets/{asset}").status_code == 404
    response = spa_client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["frontend"] is False


def test_readiness_accepts_assets_served_by_spa_fallback(settings):
    dist = settings.frontend_dist
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!doctype html><script src="assets/app.js"></script><link rel="stylesheet" href="assets/app.css">',
        encoding="utf-8",
    )
    app = create_app(settings)
    # assets не существовала при mount_frontend; созданные файлы всё равно раздаёт SPA.
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("body { color: black; }", encoding="utf-8")
    with TestClient(app) as client:
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/app.css").status_code == 200
        response = client.get("/api/health/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["frontend"] is True


def test_missing_file_is_404(spa_client):
    response = spa_client.get("/favicon.png")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_without_dist_root_is_404(client):
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_security_headers_on_every_response(spa_client):
    """Страница приложения идёт с политикой источников, ответы API не кэшируются, и у всех
    ответов есть заголовки против подмены типа, встраивания во фрейм и утечки referer."""
    page = spa_client.get("/play/12")
    assert page.headers["Content-Security-Policy"].startswith("default-src 'self'")
    api = spa_client.get("/api/health")
    assert api.headers["Cache-Control"] == "no-store" and "Content-Security-Policy" not in api.headers
    asset = spa_client.get("/assets/app.js")
    assert "Content-Security-Policy" not in asset.headers and "Cache-Control" not in asset.headers
    error = spa_client.get("/api/nothing")
    for response in (page, api, asset, error):
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


def test_direct_index_has_same_csp(spa_client):
    root = spa_client.get("/")
    direct = spa_client.get("/index.html")
    assert direct.status_code == 200
    assert direct.headers.get("Content-Security-Policy") == root.headers["Content-Security-Policy"]
