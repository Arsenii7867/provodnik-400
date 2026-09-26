"""Настройки читаются из окружения, имеют безопасные умолчания и совпадают с .env.example."""

import re
from pathlib import Path

import pytest

from app.config import BACKEND_DIR, MAX_GRACE_SECONDS, load_settings

ENV_NAMES = (
    "DATABASE_URL",
    "CONTENT_DIR",
    "AUTO_SEED",
    "APP_ENV",
    "CORS_ORIGINS",
    "INTEGRATION_API_KEY",
    "FRONTEND_DIST",
    "TOKEN_TTL_HOURS",
    "TIMER_GRACE_SECONDS",
    "LOGIN_RATE_PER_MINUTE",
    "DEMO_PIN",
)


def test_defaults_without_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert settings.app_env == "dev"
    assert settings.integration_api_key == "demo-integration-key"
    assert settings.auto_seed is True
    assert settings.cors_origins == ("http://localhost:5173", "http://127.0.0.1:5173")
    assert settings.content_dir == BACKEND_DIR.parent / "content"


def test_env_overrides_and_relative_paths(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.local, http://b.local")
    monkeypatch.setenv("CONTENT_DIR", "../content")
    monkeypatch.setenv("TIMER_GRACE_SECONDS", "2.5")
    settings = load_settings()
    assert settings.cors_origins == ("http://a.local", "http://b.local")
    assert settings.content_dir.is_absolute()
    assert settings.content_dir == (BACKEND_DIR.parent / "content").resolve()
    assert settings.timer_grace_seconds == 2.5


def test_prod_requires_integration_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("DEMO_PIN", "7391")
    monkeypatch.delenv("INTEGRATION_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("INTEGRATION_API_KEY", "секрет-из-окружения")
    assert load_settings().integration_api_key == "секрет-из-окружения"


def test_prod_requires_custom_demo_pin(monkeypatch):
    """Сид в prod не должен молча создавать демо-аккаунты с PIN из README."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("INTEGRATION_API_KEY", "секрет-из-окружения")
    monkeypatch.delenv("DEMO_PIN", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("DEMO_PIN", "1234")
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("DEMO_PIN", "7391")
    assert load_settings().demo_pin == "7391"


def test_negative_grace_rejected(monkeypatch):
    monkeypatch.setenv("TIMER_GRACE_SECONDS", "-1")
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("TIMER_GRACE_SECONDS", "0")
    assert load_settings().timer_grace_seconds == 0.0


def test_grace_is_capped(monkeypatch):
    """Окно допуска двустороннее: слишком большой допуск отдал бы таймер клиенту."""
    monkeypatch.setenv("TIMER_GRACE_SECONDS", "30")
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("TIMER_GRACE_SECONDS", str(MAX_GRACE_SECONDS))
    assert load_settings().timer_grace_seconds == MAX_GRACE_SECONDS


def test_env_example_matches_config():
    example = (BACKEND_DIR.parent / ".env.example").read_text(encoding="utf-8")
    declared = set(re.findall(r"^([A-Z_]+)=", example, flags=re.M))
    source = (Path(BACKEND_DIR) / "app" / "config.py").read_text(encoding="utf-8")
    assert declared == set(ENV_NAMES)
    for name in declared:
        assert name in source, f"{name} есть в .env.example, но config.py его не читает"
