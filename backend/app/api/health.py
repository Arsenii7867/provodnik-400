from fastapi import APIRouter, Request
from sqlalchemy.engine import make_url

from app import __version__
from app.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["Здоровье"])


@router.get("/health", summary="Состояние сервиса", response_model=HealthResponse)
def health(request: Request):
    settings = request.app.state.settings
    # сценарии появятся вместе с загрузчиком контента; до него сервер честно отвечает нулём
    return HealthResponse(
        status="ok",
        version=__version__,
        scenarios=0,
        db=make_url(settings.database_url).get_backend_name(),
    )
