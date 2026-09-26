"""Регрессии границ продакшена, лимита входа и повторов запросов."""

from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, clock, ratelimit
from app.config import load_settings
from app.errors import ApiError
from app.main import create_app
from app.models import Employee


@pytest.mark.parametrize("key", ["demo-integration-key", " demo-integration-key ", "   "])
def test_prod_rejects_public_or_blank_integration_key(monkeypatch, key):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("DEMO_PIN", "7391")
    monkeypatch.setenv("INTEGRATION_API_KEY", key)
    with pytest.raises(RuntimeError, match="INTEGRATION_API_KEY"):
        load_settings()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_timer_grace_rejected(monkeypatch, value):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TIMER_GRACE_SECONDS", value)
    with pytest.raises(RuntimeError, match="TIMER_GRACE_SECONDS"):
        load_settings()


@pytest.mark.parametrize("name", ["TOKEN_TTL_HOURS", "LOGIN_RATE_PER_MINUTE"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_security_limits_must_be_positive(monkeypatch, name, value):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=name):
        load_settings()


@pytest.mark.parametrize("auto_seed", [True, False])
def test_prod_rejects_existing_public_demo_credentials(settings, auto_seed):
    prod = replace(
        settings, app_env="prod", integration_api_key="private-test-key", demo_pin="7391", auto_seed=auto_seed
    )
    app = create_app(prod)
    with app.state.session_factory() as db:
        before = {row.id: row.pin_hash for row in db.scalars(select(Employee))}
    with pytest.raises(RuntimeError, match="PIN"):
        with TestClient(app):
            pass
    with app.state.session_factory() as db:
        assert {row.id: row.pin_hash for row in db.scalars(select(Employee))} == before


def test_prod_accepts_existing_custom_demo_credentials(settings):
    prod = replace(settings, app_env="prod", integration_api_key="private-test-key", demo_pin="7391")
    app = create_app(prod)
    with app.state.session_factory() as db:
        for employee in db.scalars(select(Employee)):
            employee.pin_hash = auth.hash_pin(prod.demo_pin, employee.pin_salt)
        db.commit()
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"employee_code": "VSM-2001", "pin": prod.demo_pin})
        assert response.status_code == 200


def test_limiter_reaps_expired_distinct_keys_without_losing_live_limits():
    now = clock.now()
    for index in range(100):
        ratelimit.check(f"old-{index}", now, 1)
    ratelimit.check("recent", now + timedelta(seconds=50), 1)
    ratelimit.check("new", now + timedelta(seconds=61), 1)
    assert not any(key.startswith("old-") for key in ratelimit._attempts)
    with pytest.raises(ApiError) as exc:
        ratelimit.check("recent", now + timedelta(seconds=61), 1)
    assert exc.value.status == 429


def test_idempotency_key_rejects_different_service_class(client, login):
    headers = login() | {"Idempotency-Key": "class-conflict"}
    body = {"scenario_id": "medical_chest_pain", "service_class": "business"}
    first = client.post("/api/sessions", headers=headers, json=body)
    assert first.status_code == 201
    replay = client.post("/api/sessions", headers=headers, json=body)
    assert replay.status_code == 200
    assert replay.json()["run_id"] == first.json()["run_id"]
    conflict = client.post("/api/sessions", headers=headers, json=body | {"service_class": "first"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_mismatch"
    assert (
        client.get("/api/sessions/active", headers=headers).json()["active"]["run_id"]
        == first.json()["run_id"]
    )
