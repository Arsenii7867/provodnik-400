"""Живость и готовность сервиса: база, проверенный контент и собранный интерфейс."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.schemas import HealthResponse, ReadinessResponse

router = APIRouter(prefix="/api", tags=["Здоровье"])


@router.head("/health", include_in_schema=False)
def health_head():
    # проверки живости с прокси и мониторинга ходят HEAD, а Starlette сам HEAD к GET не добавляет
    return Response()


@router.get("/health", summary="Состояние сервиса", response_model=HealthResponse)
def health(request: Request):
    settings = request.app.state.settings
    store = request.app.state.store
    return HealthResponse(
        status="ok",
        version=__version__,
        scenarios=len(store.scenarios()),
        db=make_url(settings.database_url).get_backend_name(),
        content_errors=len(store.errors),
    )


@router.get(
    "/health/ready",
    summary="Готовность принимать пользователей",
    response_model=ReadinessResponse,
    responses={503: {"description": "База, контент или интерфейс ещё не готовы"}},
)
def readiness(request: Request, response: Response):
    """Readiness для Compose и балансировщика; в отличие от живости проверяет зависимости."""
    settings = request.app.state.settings
    store = request.app.state.store
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ready = True
    except SQLAlchemyError:
        database_ready = False

    scenarios = len(store.scenarios())
    checks = {
        "database": database_ready,
        "content": scenarios > 0 and not store.errors,
        "frontend": (settings.frontend_dist / "index.html").is_file(),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        version=__version__,
        scenarios=scenarios,
        db=make_url(settings.database_url).get_backend_name(),
        content_errors=len(store.errors),
        checks=checks,
    )
