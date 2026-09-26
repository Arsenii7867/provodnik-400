"""Pydantic-модели тел запросов и ответов. Тела запросов только через модели, чтобы в OpenAPI
не появлялись безымянные схемы Body_; формы ответов повторяют документацию API."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    scenarios: int
    db: str
    content_errors: int


class LoginRequest(BaseModel):
    employee_code: str = Field(min_length=1, max_length=32)
    pin: str = Field(min_length=1, max_length=32)


class EmployeeOut(BaseModel):
    employee_code: str
    display_name: str
    role: str
    brigade: str
    depot: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    employee: EmployeeOut


class OkResponse(BaseModel):
    ok: bool


class DemoAccount(EmployeeOut):
    note: str


class ScenarioCard(BaseModel):
    id: str
    title: str
    summary: str
    difficulty: int
    critical: bool
    service_class: str
    service_class_title: str
    competencies: list[str]
    competencies_titles: list[str]
    estimated_minutes: int
    tags: list[str]
    has_timers: bool
    node_count: int
    endings_count: int
    best_outcome: str | None
    runs_count: int


class ContextOut(BaseModel):
    service_class: str
    service_class_title: str
    layout: str
    wait_minutes: int | None
    loyalty_sensitivity: float | None
    segment: str | None
    next_station_minutes: int | None
    time_of_day: str | None
    passenger: dict | None
    loyalty_of: str | None
    crew_available: list[str]


class ScenarioDetail(ScenarioCard):
    version: int
    role_model: bool
    source_situations: list[int]
    context: ContextOut
    paths: int
    outcomes: dict[str, int]


class FilterOption(BaseModel):
    code: str
    title: str


class FiltersResponse(BaseModel):
    competencies: list[FilterOption]
    classes: list[FilterOption]
    difficulties: list[int]


class GraphResponse(BaseModel):
    scenario_id: str
    title: str
    nodes: list[dict]
    edges: list[dict]
    paths: int
    outcomes: dict[str, int]
    scale_ranges: dict
    mermaid: str
    yaml_excerpt: str


class StartSessionRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=64)
    service_class: str | None = None


class ChooseRequest(BaseModel):
    option_id: str = Field(min_length=1, max_length=64)
    step_no: int = Field(ge=0)


class ExpireRequest(BaseModel):
    step_no: int = Field(ge=0)


class OptionOut(BaseModel):
    id: str
    text: str
    role_step: str | None
    escalation_target: str | None


class NodeOut(BaseModel):
    id: str
    type: str
    text: str
    passenger_says: str | None
    title: str | None
    timer_seconds: int | None
    options: list[OptionOut]


class LastStepOut(BaseModel):
    step_no: int
    node_id: str
    option_id: str | None
    expired: bool
    loyalty_before: int
    safety_before: int
    loyalty_after: int
    safety_after: int
    effects: dict
    competencies: dict
    delayed_applied: list[dict]
    role_step: str | None


class RoleChainOut(BaseModel):
    steps: list[str]
    next_expected: str | None
    complete: bool


class RunState(BaseModel):
    run_id: int
    scenario_id: str
    title: str
    status: str
    step_no: int
    loyalty: int
    safety: int
    flags: dict
    node: NodeOut
    deadline_at: str | None
    server_now: str
    expired: bool
    last_step: LastStepOut | None
    context: ContextOut
    role_chain: RoleChainOut
    expired_timers: int
    timers_answered: int
    outcome: str | None
    xp: int | None


class ActiveResponse(BaseModel):
    active: RunState | None
