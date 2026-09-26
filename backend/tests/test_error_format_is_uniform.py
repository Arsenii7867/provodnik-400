"""Любая ошибка API приходит в одном формате: {"error": {"code", "message", "details"}},
без стека и без внутренних подробностей."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def error_of(response):
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    return body["error"]


@pytest.fixture
def crash_client(settings):
    # маршрут-пробник: другого честного способа вызвать необработанное исключение нет
    app = create_app(settings)

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


def test_validation_error_is_422_with_fields(client):
    response = client.post("/api/auth/login", json={"employee_code": "VSM-1001"})
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert error["details"]["errors"][0]["loc"] == ["body", "pin"]


def test_unexpected_error_is_500_without_traceback(crash_client):
    response = crash_client.get("/api/probe/crash")
    assert response.status_code == 500
    assert error_of(response)["code"] == "internal_error"
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_framework_messages_are_russian(client):
    """Текст фреймворка (Not Found, Method Not Allowed, ошибка разбора тела) наружу не уходит."""
    not_found = client.get("/api/nothing")
    wrong_method = client.post("/api/health")
    broken_body = client.post(
        "/api/auth/login", content=b"\xff\xfe{", headers={"Content-Type": "application/json"}
    )
    assert broken_body.status_code in (400, 422)
    for response in (not_found, wrong_method, broken_body):
        message = error_of(response)["message"]
        assert message and not any("a" <= letter.lower() <= "z" for letter in message), message


def test_oversized_body_is_413_in_uniform_format(client):
    from app.http_security import MAX_BODY_BYTES

    response = client.post(
        "/api/auth/login", content=b"0" * (MAX_BODY_BYTES + 1), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert error_of(response)["code"] == "payload_too_large"
