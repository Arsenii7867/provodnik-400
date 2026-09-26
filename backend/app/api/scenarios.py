from fastapi import APIRouter, Request
from sqlalchemy import select

from app.auth import CurrentEmployee
from app.db import Db
from app.errors import ApiError
from app.models import ScenarioRun
from app.scenarios import graph
from app.scenarios.engine import OUTCOMES
from app.schemas import FiltersResponse, GraphResponse, ScenarioCard, ScenarioDetail
from app.services.session_service import context_view

router = APIRouter(prefix="/api/scenarios", tags=["Сценарии"])


def run_results(db, employee):
    """Число завершённых прохождений и лучший исход по каждому сценарию для карточек каталога."""
    rows = db.execute(
        select(ScenarioRun.scenario_id, ScenarioRun.outcome).where(
            ScenarioRun.employee_id == employee.id, ScenarioRun.status == "finished"
        )
    ).all()
    results = {}
    for scenario_id, outcome in rows:
        entry = results.setdefault(scenario_id, {"runs_count": 0, "best_outcome": None})
        entry["runs_count"] += 1
        best = entry["best_outcome"]
        if best is None or OUTCOMES.index(outcome) > OUTCOMES.index(best):
            entry["best_outcome"] = outcome
    return results


def card_view(scenario, content, result):
    nodes = scenario["nodes"]
    titles = {item["code"]: item["title"] for item in content.competencies}
    service_class = scenario["context"]["service_class"]
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "summary": scenario["summary"],
        "difficulty": scenario["difficulty"],
        "critical": bool(scenario.get("critical")),
        "service_class": service_class,
        "service_class_title": content.classes[service_class]["title"],
        "competencies": list(scenario["competencies"]),
        "competencies_titles": [titles.get(code, code) for code in scenario["competencies"]],
        "estimated_minutes": scenario["estimated_minutes"],
        "tags": list(scenario.get("tags") or []),
        "has_timers": any(node.get("timer") for node in nodes.values()),
        "node_count": len(nodes),
        "endings_count": sum(node["type"] == "ending" for node in nodes.values()),
        "best_outcome": result["best_outcome"] if result else None,
        "runs_count": result["runs_count"] if result else 0,
    }


def outcome_counts(analysis):
    own = analysis["own"]["outcomes"] if analysis else {}
    return {outcome: own.get(outcome, 0) for outcome in OUTCOMES}


def matches(scenario, competency, difficulty, service_class, critical):
    if competency and competency not in scenario["competencies"]:
        return False
    if difficulty is not None and scenario["difficulty"] != difficulty:
        return False
    if service_class and scenario["context"]["service_class"] != service_class:
        return False
    if critical is not None and bool(scenario.get("critical")) != critical:
        return False
    return True


def scenario_or_404(store, scenario_id):
    scenario = store.scenario(scenario_id)
    if scenario is None:
        raise ApiError(404, "scenario_not_found", f"Сценария {scenario_id} нет в каталоге")
    return scenario


@router.get("", summary="Каталог сценариев с фильтрами", response_model=list[ScenarioCard])
def list_scenarios(
    request: Request,
    employee: CurrentEmployee,
    db: Db,
    competency: str | None = None,
    difficulty: int | None = None,
    service_class: str | None = None,
    critical: bool | None = None,
):
    content = request.app.state.store.content()
    results = run_results(db, employee)
    return [
        card_view(content.scenarios[scenario_id], content, results.get(scenario_id))
        for scenario_id in sorted(content.scenarios)
        if matches(content.scenarios[scenario_id], competency, difficulty, service_class, critical)
    ]


@router.get("/filters", summary="Значения фильтров каталога", response_model=FiltersResponse)
def filters(request: Request, employee: CurrentEmployee):
    content = request.app.state.store.content()
    # при сломанных справочниках на первом старте каталог пуст, и фильтры честно пустые, а не 500
    limits = (content.rules.get("limits") or {}).get("difficulty") or {}
    return {
        "competencies": [{"code": item["code"], "title": item["title"]} for item in content.competencies],
        "classes": [{"code": code, "title": item["title"]} for code, item in content.classes.items()],
        "difficulties": list(range(limits["min"], limits["max"] + 1)) if limits else [],
    }


@router.get("/{scenario_id}", summary="Карточка сценария", response_model=ScenarioDetail)
def scenario_detail(scenario_id: str, request: Request, employee: CurrentEmployee, db: Db):
    store = request.app.state.store
    scenario = scenario_or_404(store, scenario_id)
    content = store.content()
    analysis = store.analysis(scenario_id)
    card = card_view(scenario, content, run_results(db, employee).get(scenario_id))
    return card | {
        "version": scenario.get("version", 1),
        "role_model": bool(scenario.get("role_model")),
        "source_situations": list(scenario.get("source_situations") or []),
        "context": context_view(scenario, content, scenario["context"]["service_class"]),
        "paths": analysis["own"]["paths"] if analysis else 0,
        "outcomes": outcome_counts(analysis),
    }


@router.get(
    "/{scenario_id}/graph",
    summary="Граф сценария: узлы, рёбра, пути, Mermaid",
    response_model=GraphResponse,
)
def scenario_graph(scenario_id: str, request: Request, employee: CurrentEmployee, db: Db):
    store = request.app.state.store
    scenario = scenario_or_404(store, scenario_id)
    # карта раскрывает все ветки: проводник видит её после первого прохождения, наставник всегда
    if employee.role != "mentor" and scenario_id not in run_results(db, employee):
        raise ApiError(403, "graph_locked", "Карта сценария откроется после первого прохождения")
    analysis = store.analysis(scenario_id)
    built = graph.build_graph(scenario, analysis, store.source_text(scenario_id))
    built["outcomes"] = outcome_counts(analysis)
    return built | {"scenario_id": scenario_id, "title": scenario["title"]}
