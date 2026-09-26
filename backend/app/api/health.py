"""Состояние сервиса: версия, число сценариев в каталоге, диалект базы и число ошибок контента,
по которому видно, что сервер живёт на прежней версии сценариев."""

from fastapi import APIRouter, Request, Response
from sqlalchemy.engine import make_url

from app import __version__
from app.schemas import HealthResponse

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
