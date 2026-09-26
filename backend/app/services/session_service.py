"""Прохождение сценария на сервере: старт, выбор, истечение и отказ; итог и всё, что он
запускает, считает completion.py в той же транзакции. Состояние движка лежит в
scenario_runs.state_json, каждый ход пишется в run_steps и action_log. Переход шага делается
условным UPDATE по step_no, поэтому двойной клик и гонка «истечение плюс выбор» дают 409, а не
второй ход. Время приходит аргументом now из clock.now()."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app import clock
from app.errors import ApiError
from app.models import RunStep, ScenarioRun
from app.scenarios import engine
from app.services import action_log, completion

TIME_FIELDS = ("node_entered_at", "deadline_at")


def serialize_state(state):
    data = dict(state)
    for name in TIME_FIELDS:
        data[name] = state[name].isoformat() if state[name] else None
    return data


def deserialize_state(data):
    state = dict(data)
    for name in TIME_FIELDS:
        state[name] = datetime.fromisoformat(data[name]) if data[name] else None
    return state


def engine_error(exc):
    """Отказ движка становится ответом API с тем же кодом; неизвестный класс это ошибка тела запроса."""
    if exc.code == "unknown_class":
        details = {"errors": [{"loc": ["body", "service_class"], "msg": exc.message}]}
        return ApiError(422, "validation_error", exc.message, details)
    return ApiError(409, exc.code, exc.message)


def find_by_key(db, employee, idempotency_key):
    return db.scalar(
        select(ScenarioRun).where(
            ScenarioRun.employee_id == employee.id, ScenarioRun.idempotency_key == idempotency_key
        )
    )


def reuse_run(existing, scenario_id, service_class):
    # Отсутствующий класс уже выбран при старте: живая правка YAML не меняет повтор запроса.
    if existing.scenario_id != scenario_id or (service_class and existing.service_class != service_class):
        message = "Этот Idempotency-Key уже использован для другого сценария или класса"
        raise ApiError(409, "idempotency_mismatch", message, {"scenario_id": existing.scenario_id})
    return existing, False


def start_run(db, store, employee, scenario_id, service_class, idempotency_key, now):
    """Возвращает пару (прохождение, создано ли оно сейчас): повтор с тем же Idempotency-Key
    отдаёт прежнее прохождение, чтобы двойная отправка формы не открывала второе."""
    if idempotency_key:
        existing = find_by_key(db, employee, idempotency_key)
        if existing is not None:
            return reuse_run(existing, scenario_id, service_class)
    scenario = store.scenario(scenario_id)
    if scenario is None:
        raise ApiError(404, "scenario_not_found", f"Сценария {scenario_id} нет в каталоге")
    try:
        state = engine.start(scenario, store.content(), now, service_class)
    except engine.EngineError as exc:
        raise engine_error(exc) from exc
    # у сотрудника одно активное прохождение: новый старт закрывает прежние
    db.execute(
        update(ScenarioRun)
        .where(ScenarioRun.employee_id == employee.id, ScenarioRun.status == "active")
        .values(status="abandoned", finished_at=now)
    )
    run = ScenarioRun(
        employee_id=employee.id,
        scenario_id=scenario_id,
        scenario_version=scenario.get("version", 1),
        service_class=state["service_class"],
        status="active",
        current_node=state["node"],
        step_no=0,
        state_json=serialize_state(state),
        node_entered_at=now,
        deadline_at=state["deadline_at"],
        started_at=now,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        # параллельный повтор с тем же ключом успел первым: отдаём его прохождение
        db.rollback()
        existing = find_by_key(db, employee, idempotency_key) if idempotency_key else None
        if existing is None:
            raise
        return reuse_run(existing, scenario_id, service_class)
    payload = {"scenario_id": scenario_id, "service_class": state["service_class"]}
    action_log.log(db, employee.id, "run_started", "run", run.id, payload, now)
    db.commit()
    return run, True


def get_run(db, employee, run_id):
    run = db.get(ScenarioRun, run_id)
    if run is None:
        raise ApiError(404, "run_not_found", "Прохождения с таким номером нет")
    if run.employee_id != employee.id:
        raise ApiError(403, "foreign_run", "Это прохождение другого сотрудника")
    return run


def active_run(db, employee):
    return db.scalar(
        select(ScenarioRun)
        .where(ScenarioRun.employee_id == employee.id, ScenarioRun.status == "active")
        .order_by(ScenarioRun.id.desc())
        .limit(1)
    )


def require_step(run, step_no):
    if run.status != "active":
        raise ApiError(409, "already_finished", "Прохождение уже завершено", {"status": run.status})
    if step_no != run.step_no:
        message = "Состояние устарело: обновите прохождение и повторите ход"
        raise ApiError(409, "stale_step", message, {"expected_step_no": run.step_no})


def scenario_for(db, store, run, now):
    """Сценарий и контент одной версии; если текущего узла в файле больше нет, прохождение закрывается."""
    content = store.content()
    scenario = content.scenarios.get(run.scenario_id)
    if scenario is None or run.current_node not in scenario["nodes"]:
        close_run(db, run, now)
        raise ApiError(409, "run_not_active", "Сценарий изменился, начните прохождение заново")
    return scenario, content


def load_state(run, scenario):
    state = deserialize_state(run.state_json)
    if state["deadline_at"] is not None and not scenario["nodes"][state["node"]].get("timer"):
        # таймер сняли живой правкой уже после входа в узел: старый дедлайн больше не действует
        state["deadline_at"] = None
    return state


def choose(db, store, run, option_id, step_no, now, grace_seconds):
    require_step(run, step_no)
    scenario, content = scenario_for(db, store, run, now)
    state = load_state(run, scenario)
    try:
        state, step = engine.apply_choice(scenario, content, state, option_id, now, grace_seconds)
    except engine.EngineError as exc:
        raise engine_error(exc) from exc
    commit_step(db, run, scenario, content, state, step, now)
    return step


def expire(db, store, run, step_no, now, grace_seconds):
    require_step(run, step_no)
    scenario, content = scenario_for(db, store, run, now)
    state = load_state(run, scenario)
    try:
        state, step = engine.apply_expiry(scenario, content, state, now, grace_seconds)
    except engine.EngineError as exc:
        raise engine_error(exc) from exc
    commit_step(db, run, scenario, content, state, step, now)
    return step


def commit_step(db, run, scenario, content, state, step, now):
    values = {
        "state_json": serialize_state(state),
        "status": state["status"],
        "current_node": state["node"],
        "step_no": state["step_no"],
        "node_entered_at": state["node_entered_at"],
        "deadline_at": state["deadline_at"],
        "expired_timers": state["expired_timers"],
        "timers_answered": state["timers_answered"],
    }
    finished = state["status"] == "finished"
    if finished:
        values.update(completion.finish_run(db, run, content, state, now))
    result = db.execute(
        update(ScenarioRun)
        .where(
            ScenarioRun.id == run.id,
            ScenarioRun.step_no == step["step_no"] - 1,
            ScenarioRun.status == "active",
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        db.refresh(run)
        details = {"expected_step_no": run.step_no, "status": run.status}
        raise ApiError(409, "stale_step", "Этот ход уже сделан: обновите состояние прохождения", details)
    db.add(RunStep(**step_row(run.id, scenario, step, now)))
    action = "timer_expired" if step["expired"] else "option_chosen"
    payload = {"step_no": step["step_no"], "node_id": step["node_id"], "option_id": step["option_id"]}
    action_log.log(db, run.employee_id, action, "run", run.id, payload, now)
    if finished:
        # итог уже записан условным UPDATE, поэтому история и шаги ниже видят это прохождение завершённым
        completion.complete_run(db, run, scenario, content, values, now)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "stale_step", "Этот ход уже записан: обновите состояние прохождения") from None
    db.refresh(run)


def action_source(scenario, node_id, option_id, expired):
    """Источник хода в сценарии: вариант диалога, сам узел-событие или ветка истечения."""
    node = (scenario.get("nodes") or {}).get(node_id) or {}
    if expired:
        return (node.get("timer") or {}).get("on_expire") or {}
    if node.get("type") == "event":
        return node
    return next((option for option in node.get("options") or [] if option["id"] == option_id), {})


def step_row(run_id, scenario, step, now):
    node = scenario["nodes"][step["node_id"]]
    source = action_source(scenario, step["node_id"], step["option_id"], step["expired"])
    if step["expired"]:
        verdict = "expired"
    else:
        verdict = (source.get("debrief") or {}).get("verdict")
    return {
        "run_id": run_id,
        "step_no": step["step_no"],
        "node_id": step["node_id"],
        "node_text": node.get("text", ""),
        "option_id": step["option_id"],
        "option_text": source.get("text") if node["type"] == "dialog" and not step["expired"] else None,
        "expired": step["expired"],
        "loyalty_before": step["loyalty_before"],
        "safety_before": step["safety_before"],
        "loyalty_after": step["loyalty_after"],
        "safety_after": step["safety_after"],
        "effects_json": step["effects"],
        "competencies_json": step["competencies"],
        "delayed_applied_json": step["delayed_applied"],
        "role_step": source.get("role_step"),
        "escalation_target": source.get("escalation_target"),
        "verdict": verdict,
        "answered_in_seconds": step["answered_in_seconds"],
        "created_at": now,
    }


def close_run(db, run, now):
    """Перевод в abandoned только из active: финальный ход, успевший раньше, не затирается."""
    result = db.execute(
        update(ScenarioRun)
        .where(ScenarioRun.id == run.id, ScenarioRun.status == "active")
        .values(status="abandoned", finished_at=now)
        .execution_options(synchronize_session=False)
    )
    closed = result.rowcount == 1
    if closed:
        payload = {"node_id": run.current_node}
        action_log.log(db, run.employee_id, "run_abandoned", "run", run.id, payload, now)
    db.commit()
    db.refresh(run)
    return closed


def abandon(db, run, now):
    if run.status != "active" or not close_run(db, run, now):
        raise ApiError(409, "already_finished", "Прохождение уже завершено", {"status": run.status})
    return run


def context_view(scenario, content, service_class):
    context = scenario.get("context") or {}
    service = content.classes.get(service_class) or {}
    return {
        "service_class": service_class,
        "service_class_title": service.get("title", service_class),
        "layout": service.get("layout", ""),
        "wait_minutes": service.get("wait_minutes"),
        "loyalty_sensitivity": service.get("loyalty_sensitivity"),
        "segment": context.get("segment"),
        "next_station_minutes": context.get("next_station_minutes"),
        "time_of_day": context.get("time_of_day"),
        "passenger": context.get("passenger"),
        "loyalty_of": context.get("loyalty_of"),
        "crew_available": list(context.get("crew_available") or []),
    }


def option_view(option):
    return {
        "id": option["id"],
        "text": option["text"],
        "role_step": option.get("role_step"),
        "escalation_target": option.get("escalation_target"),
    }


def last_step_view(scenario, state):
    if not state["steps"]:
        return None
    step = state["steps"][-1]
    source = action_source(scenario, step["node_id"], step["option_id"], step["expired"])
    keys = (
        "step_no",
        "node_id",
        "option_id",
        "expired",
        "loyalty_before",
        "safety_before",
        "loyalty_after",
        "safety_after",
        "effects",
        "competencies",
        "delayed_applied",
    )
    view = {key: step[key] for key in keys}
    view["role_step"] = source.get("role_step")
    return view


def state_view(run, store, now, step=None):
    """Ответ API о прохождении; expired это свойство ответа (истечение применено этим ходом),
    а не прохождения. Варианты берутся из текущего файла сценария: живая правка видна сразу."""
    content = store.content()
    scenario = content.scenarios.get(run.scenario_id) or {}
    state = deserialize_state(run.state_json)
    node = (scenario.get("nodes") or {}).get(state["node"]) or {}
    options = []
    if run.status == "active" and node.get("type") == "dialog":
        options = engine.available_options(scenario, state)
    # дедлайн записан при входе в узел; секунды считаются от него, а не из файла, который могли поправить
    deadline = run.deadline_at if run.status == "active" and node.get("timer") else None
    timer_seconds = round((deadline - state["node_entered_at"]).total_seconds()) if deadline else None
    return {
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "title": scenario.get("title", run.scenario_id),
        "status": run.status,
        "step_no": run.step_no,
        "loyalty": state["loyalty"],
        "safety": state["safety"],
        "flags": state["flags"],
        "node": {
            "id": state["node"],
            "type": node.get("type", "dialog"),
            "text": node.get("text", ""),
            "passenger_says": node.get("passenger_says"),
            "title": node.get("title"),
            "timer_seconds": timer_seconds,
            "options": [option_view(option) for option in options],
        },
        "deadline_at": clock.iso(deadline),
        "server_now": clock.iso(now),
        "expired": bool(step and step["expired"]),
        "last_step": last_step_view(scenario, state),
        "context": context_view(scenario, content, state["service_class"]),
        "role_chain": engine.role_chain_progress(state),
        "expired_timers": state["expired_timers"],
        "timers_answered": state["timers_answered"],
        "outcome": run.outcome,
        "xp": run.xp_earned,
    }
