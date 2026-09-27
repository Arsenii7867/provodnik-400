"""Разбор завершённого прохождения: снимок при завершении или явно обозначенный legacy fallback."""

from fastapi import APIRouter, Request

from app.auth import CurrentEmployee
from app.db import Db, EntityId
from app.errors import ApiError
from app.schemas import DebriefResponse
from app.services import debrief as history
from app.services import session_service

router = APIRouter(prefix="/api/runs", tags=["Разбор"])


@router.get(
    "/{run_id}/debrief",
    summary="Разбор завершённого прохождения по шагам",
    response_model=DebriefResponse,
)
def debrief(run_id: EntityId, request: Request, employee: CurrentEmployee, db: Db):
    run = session_service.get_run(db, employee, run_id)
    if run.status != "finished":
        message = "Разбор доступен после завершения прохождения"
        raise ApiError(409, "run_not_finished", message, {"status": run.status})
    snapshot = history.snapshot_data(run.state_json.get("debrief_snapshot"))
    if snapshot is not None:
        return snapshot
    content = request.app.state.store.content()
    scenario = content.scenarios.get(run.scenario_id) or {"title": run.scenario_id, "nodes": {}}
    result = history.render(db, content, scenario, run)
    # Без финального снимка вычисляемые поля не являются исторически зафиксированными.
    result["history_status"] = "legacy"
    return result
