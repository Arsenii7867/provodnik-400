"""Настройки сервера из переменных окружения. Список переменных и значения по умолчанию
совпадают с .env.example в корне репозитория; ничего другого код из окружения не читает."""

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
# окно допуска двустороннее: при большом допуске клиент мог бы закрывать таймер задолго до срока
MAX_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./data/provodnik.db"
    content_dir: Path = BACKEND_DIR.parent / "content"
    auto_seed: bool = True
    app_env: str = "dev"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    integration_api_key: str = "demo-integration-key"
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"
    token_ttl_hours: int = 12
    timer_grace_seconds: float = 1.0
    login_rate_per_minute: int = 10
    demo_pin: str = "1234"


def resolve_path(value):
    # относительные пути в .env считаются от папки backend, откуда запускается uvicorn
    path = Path(value)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def split_origins(value):
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def load_settings() -> Settings:
    env = os.environ
    defaults = Settings()
    app_env = env.get("APP_ENV", defaults.app_env)
    api_key = env.get("INTEGRATION_API_KEY", "" if app_env == "prod" else defaults.integration_api_key)
    if app_env == "prod" and not api_key:
        raise RuntimeError("В prod задайте INTEGRATION_API_KEY: демо-ключ там не действует")
    demo_pin = env.get("DEMO_PIN", defaults.demo_pin)
    if app_env == "prod" and demo_pin == defaults.demo_pin:
        # иначе сид молча создал бы в prod демо-аккаунты с PIN, который напечатан в README
        raise RuntimeError("В prod задайте свой DEMO_PIN: значение по умолчанию известно всем")
    grace = float(env.get("TIMER_GRACE_SECONDS", defaults.timer_grace_seconds))
    if grace < 0:
        # отрицательный допуск перевернул бы окно: поздний выбор считался бы ранним истечением
        raise RuntimeError("TIMER_GRACE_SECONDS не может быть отрицательным")
    if grace > MAX_GRACE_SECONDS:
        raise RuntimeError(f"TIMER_GRACE_SECONDS не больше {MAX_GRACE_SECONDS:g}: иначе таймер решает клиент")
    return Settings(
        database_url=env.get("DATABASE_URL", defaults.database_url),
        content_dir=resolve_path(env["CONTENT_DIR"]) if "CONTENT_DIR" in env else defaults.content_dir,
        auto_seed=env.get("AUTO_SEED", "1") == "1",
        app_env=app_env,
        cors_origins=split_origins(env["CORS_ORIGINS"]) if env.get("CORS_ORIGINS") else defaults.cors_origins,
        integration_api_key=api_key,
        frontend_dist=resolve_path(env["FRONTEND_DIST"])
        if "FRONTEND_DIST" in env
        else defaults.frontend_dist,
        token_ttl_hours=int(env.get("TOKEN_TTL_HOURS", defaults.token_ttl_hours)),
        timer_grace_seconds=grace,
        login_rate_per_minute=int(env.get("LOGIN_RATE_PER_MINUTE", defaults.login_rate_per_minute)),
        demo_pin=demo_pin,
    )
