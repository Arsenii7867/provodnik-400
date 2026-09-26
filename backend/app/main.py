"""Сборка приложения FastAPI: настройки, база, контент в памяти, CORS, обработчики ошибок,
маршруты API и раздача собранного фронта с того же порта. Таблицы и начальные данные создаются
при старте, а не при импорте. Запуск: uvicorn app.main:app --host 127.0.0.1 --port 8000."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from app import __version__, clock
from app.api import (
    achievements,
    auth,
    challenges,
    health,
    leaderboard,
    notifications,
    profile,
    runs,
    scenarios,
    sessions,
)
from app.config import Settings, load_settings
from app.db import make_engine, prepare_database
from app.errors import ApiError, install_error_handlers
from app.scenarios.store import ContentStore
from app.seed import seed

# эти префиксы обслуживает сам сервер, для них фолбэк на index.html не нужен
SERVER_PREFIXES = ("api", "docs", "redoc", "openapi.json")


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
    app = FastAPI(
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
    if (settings.frontend_dist / "index.html").exists():
        mount_frontend(app, settings.frontend_dist)
    return app


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
        return FileResponse(index)


app = create_app()
