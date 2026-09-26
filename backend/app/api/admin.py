"""Администрирование контента для наставника: перечитать сценарии и справочники с отчётом
валидатора (новые сценарии дают уведомления всем, новые челленджи открывают окно) и проверить
файлы без применения."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app import clock
from app.auth import require_role
from app.db import Db
from app.models import Employee
from app.scenarios import store as content_store
from app.scenarios import validator
from app.schemas import ReloadReport
from app.services import action_log, challenges, notifications

router = APIRouter(prefix="/api/admin", tags=["Администрирование"])
Mentor = Annotated[Employee, Depends(require_role("mentor"))]


def short_files(errors):
    # наставнику нужно имя файла и строка, а не путь на диске сервера
    return [item | {"file": Path(item["file"]).name} for item in errors]


@router.post(
    "/scenarios/reload",
    summary="Перечитать сценарии и справочники, уведомить о новых",
    response_model=ReloadReport,
)
def reload(request: Request, employee: Mentor, db: Db):
    store = request.app.state.store
    now = clock.now()
    report = store.reload()
    content = store.content()
    notified = notifications.notify_new_scenarios(db, content, report["new"], now)
    activated = challenges.activate(db, content, now)
    payload = {
        "new": report["new"],
        "removed": report["removed"],
        "errors": len(report["errors"]),
        "challenges": activated,
    }
    action_log.log(db, employee.id, "content_reloaded", "content", None, payload, now)
    db.commit()
    return report | {"errors": short_files(report["errors"]), "notified": notified}


@router.get(
    "/scenarios/validate",
    summary="Проверить файлы контента валидатором без применения",
    response_model=ReloadReport,
)
def validate(request: Request, employee: Mentor):
    store = request.app.state.store
    content, report = validator.load_validated(store.content_dir)
    current = set(store.scenarios())
    loaded = set(content.scenarios)
    return {
        "loaded": sorted(loaded),
        "new": sorted(loaded - current),
        "removed": sorted(current - loaded),
        "errors": short_files(content_store.collect_errors(store.content_dir, content, report)),
        "summary": report["summary"],
        "notified": 0,
    }
