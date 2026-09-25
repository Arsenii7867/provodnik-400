"""Сборка приложения FastAPI: настройки, CORS, обработчики ошибок, маршруты API и раздача
собранного фронта с того же порта. Запуск: uvicorn app.main:app --host 127.0.0.1 --port 8000."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import health
from app.config import Settings, load_settings
from app.errors import ApiError, install_error_handlers

# эти префиксы обслуживает сам сервер, для них фолбэк на index.html не нужен
SERVER_PREFIXES = ("api", "docs", "redoc", "openapi.json")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(
        title="Проводник 400",
        description="Тренажёр нештатных ситуаций для проводников ВСМ-400.",
        version=__version__,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
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
