"""Любая ошибка API приходит в одном формате: {"error": {"code", "message", "details"}},
без стека и без внутренних подробностей."""

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import create_app


def error_of(response):
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    return body["error"]


class Probe(BaseModel):
    seconds: int


@pytest.fixture(scope="module")
def probe_client(settings):
    # маршруты-пробники: реальных тел запросов в каркасе ещё нет, а формат 422 и 500 проверить нужно
    app = create_app(settings)

    @app.post("/api/probe/validate", include_in_schema=False)
    def validate(body: Probe):
        return {"seconds": body.seconds}

    @app.get("/api/probe/crash", include_in_schema=False)
    def crash():
        raise RuntimeError("проверка обработчика")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_unknown_route_is_404(client):
    response = client.get("/api/nothing")
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_wrong_method_is_405(client):
    response = client.post("/api/health")
    assert response.status_code == 405
    assert error_of(response)["code"] == "method_not_allowed"


def test_validation_error_is_422_with_fields(probe_client):
    response = probe_client.post("/api/probe/validate", json={"seconds": "много"})
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert error["details"]["errors"][0]["loc"] == ["body", "seconds"]


def test_unexpected_error_is_500_without_traceback(probe_client):
    response = probe_client.get("/api/probe/crash")
    assert response.status_code == 500
    assert error_of(response)["code"] == "internal_error"
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
