"""Сборка приложения FastAPI: настройки, база, контент в памяти, CORS, обработчики ошибок,
маршруты API и раздача собранного фронта с того же порта. Таблицы и начальные данные создаются
при старте, а не при импорте. Запуск: uvicorn app.main:app --host 127.0.0.1 --port 8000."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi_offline import FastAPIOffline
from sqlalchemy.orm import sessionmaker

from app import __version__, clock
from app.api import (
    achievements,
    admin,
    analytics,
    auth,
    challenges,
    health,
    integration,
    leaderboard,
    notifications,
    profile,
    runs,
    scenarios,
    sessions,
)
from app.config import Settings, load_settings
from app.db import make_engine, prepare_database
from app.errors import MESSAGES_BY_STATUS, ApiError, error_response, install_error_handlers
from app.scenarios.store import ContentStore
from app.seed import seed

# эти префиксы обслуживает сам сервер, для них фолбэк на index.html не нужен
SERVER_PREFIXES = ("api", "docs", "redoc", "openapi.json", "static-offline-docs")
# заголовки на каждом ответе; HTTPS и HSTS остаются на прокси перед сервером
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
# политика только для страницы приложения: фронт собран без внешних скриптов, стилей и шрифтов
PAGE_CSP = "; ".join(
    (
        "default-src 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
    )
)
MAX_BODY_BYTES = 1_000_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    prepare_database(app.state.engine)
    app.state.store.refresh()
    if settings.auto_seed:
        with app.state.session_factory() as db:
            seed(db, app.state.store, settings, clock.now())
    yield
    app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    # Swagger UI и ReDoc отдаются с файлов самого сервера: в контуре заказчика внешних CDN может не быть
    app = FastAPIOffline(
        title="Проводник 400",
        description="Тренажёр нештатных ситуаций для проводников ВСМ-400.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.session_factory = sessionmaker(app.state.engine)
    app.state.store = ContentStore(settings.content_dir)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    install_security(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(scenarios.router)
    app.include_router(sessions.router)
    app.include_router(runs.router)
    app.include_router(achievements.router)
    app.include_router(leaderboard.router)
    app.include_router(notifications.router)
    app.include_router(challenges.router)
    app.include_router(analytics.router)
    app.include_router(integration.router)
    app.include_router(admin.router)
    if (settings.frontend_dist / "index.html").exists():
        mount_frontend(app, settings.frontend_dist)
    return app


def with_security_headers(response, path):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if path.startswith("/api"):
        # ответы API персональные: браузер и прокси их не кэшируют
        response.headers["Cache-Control"] = "no-store"
    return response


def install_security(app: FastAPI):
    """Заголовки безопасности на каждом ответе и предел заявленного размера тела; поток без
    Content-Length ограничивает прокси."""

    @app.middleware("http")
    async def security(request: Request, call_next):
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_BODY_BYTES:
            rejected = error_response(413, "payload_too_large", MESSAGES_BY_STATUS[413])
            return with_security_headers(rejected, request.url.path)
        return with_security_headers(await call_next(request), request.url.path)


def mount_frontend(app: FastAPI, dist: Path):
    """Раздача собранного фронта: ассеты как файлы, остальные пути отдают index.html, чтобы
    маршруты React открывались по прямой ссылке и после обновления страницы."""
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.split("/", 1)[0] in SERVER_PREFIXES:
            raise ApiError(404, "not_found", "Такого адреса нет")
        candidate = (dist / path).resolve() if path else index
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        if Path(path).suffix:
            raise ApiError(404, "not_found", "Файла нет")
        page = FileResponse(index)
        page.headers["Content-Security-Policy"] = PAGE_CSP
        return page


app = create_app()
