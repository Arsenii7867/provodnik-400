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


class LevelOut(BaseModel):
    id: str
    title: str
    threshold: int
    next_threshold: int | None
    next_title: str | None


class CompetencyOut(BaseModel):
    code: str
    title: str
    mastery: float | None
    status: str
    earned: int
    assessed: int
    runs_assessed: int


class LastRunOut(BaseModel):
    run_id: int
    scenario_id: str
    title: str
    outcome: str
    xp: int
    score: int
    finished_at: str


class ExpiringBonusOut(BaseModel):
    points: int
    reason: str
    expires_at: str


class BonusOut(BaseModel):
    active_total: int
    expiring: list[ExpiringBonusOut]


class ProfileResponse(EmployeeOut):
    xp_total: int
    level: LevelOut
    xp_to_next: int | None
    competencies: list[CompetencyOut]
    achievements_count: int
    achievements_total: int
    runs_count: int
    rank_brigade: int | None
    last_run: LastRunOut | None
    bonus: BonusOut


class RunHistoryItem(BaseModel):
    run_id: int
    scenario_id: str
    title: str
    status: str
    outcome: str | None
    loyalty_final: int | None
    safety_final: int | None
    score: int | None
    xp: int | None
    started_at: str
    finished_at: str | None
    expired_timers: int
    service_class: str


class RefOut(BaseModel):
    key: str
    kind: str
    title: str
    quote: str
    phrase: str
    document: str
    clause: str
    number: int | None
    reconstructed: bool


class BestOptionOut(BaseModel):
    id: str
    text: str


class DelayedAppliedOut(BaseModel):
    text: str
    effects: dict
    cancelled: bool


class DebriefStep(BaseModel):
    step_no: int
    node_id: str
    node_text: str
    passenger_says: str | None
    option_id: str | None
    option_text: str | None
    expired: bool
    timer_seconds: int | None
    answered_in_seconds: float | None
    verdict: str | None
    why: str | None
    better: str | None
    best_option: BestOptionOut | None
    refs: list[RefOut]
    loyalty_before: int
    loyalty_after: int
    safety_before: int
    safety_after: int
    effects: dict
    competencies: dict
    delayed_applied: list[DelayedAppliedOut]
    role_step: str | None
    escalation_target: str | None


class EndingOut(BaseModel):
    id: str
    title: str
    text: str
    summary: str
    refs: list[RefOut]


class AchievementNewOut(BaseModel):
    id: str
    title: str
    description: str


class CompetencyDeltaOut(BaseModel):
    code: str
    title: str
    earned: int
    assessed: int
    mastery_before: float | None
    mastery_after: float | None
    status: str


class XpBreakdownOut(BaseModel):
    base: int
    scales: int
    tempo: int
    role: int


class ChallengeCompletedOut(BaseModel):
    id: str
    title: str
    bonus_points: int
    bonus_expires_at: str


class DebriefResponse(BaseModel):
    run_id: int
    scenario_id: str
    title: str
    service_class: str
    outcome: str
    loyalty_start: int
    safety_start: int
    loyalty_final: int
    safety_final: int
    xp: int
    xp_breakdown: XpBreakdownOut
    score: int
    is_repeat: bool
    expired_timers: int
    timers_answered: int
    role_chain: RoleChainOut
    steps: list[DebriefStep]
    ending: EndingOut
    achievements_new: list[AchievementNewOut]
    challenges_completed: list[ChallengeCompletedOut]
    competencies_delta: list[CompetencyDeltaOut]
    level_before: LevelOut
    level_after: LevelOut


class AchievementOut(BaseModel):
    id: str
    title: str
    description: str
    rule_text: str
    rule_type: str
    earned: bool
    earned_at: str | None


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    payload: dict
    created_at: str
    read_at: str | None


class ReadAllResponse(BaseModel):
    read: int


class LeaderboardRow(BaseModel):
    rank: int
    employee_code: str
    display_name: str
    brigade: str
    depot: str
    score: int
    best_scores_sum: int
    bonus_points: int
    achievements: int
    is_me: bool


class LeaderboardResponse(BaseModel):
    scope: str
    scope_title: str
    rows: list[LeaderboardRow]
    me: LeaderboardRow | None


class RecommendationOut(BaseModel):
    scenario_id: str
    title: str
    competency: str | None
    reason: str


class MistakeOut(BaseModel):
    competency: str
    title: str
    count: int
    last_scenario_id: str


class TempoOut(BaseModel):
    answered_avg_seconds: float | None
    timers_answered: int
    timers_expired: int
    on_time_share: float | None


class EscalationOut(BaseModel):
    critical_runs: int
    on_time: int
    share: float | None
    needless: int


class WeekOut(BaseModel):
    week_start: str
    runs: int
    avg_score: int | None
    incidents: int
    xp: int


class AnalyticsMeResponse(BaseModel):
    competencies: list[CompetencyOut]
    weak: list[str]
    gaps: list[str]
    mistakes: list[MistakeOut]
    recommendations: list[RecommendationOut]
    tempo: TempoOut
    escalation: EscalationOut
    weekly: list[WeekOut]
    summary: str
    runs_total: int
    last_run_at: str | None


class BrigadeOut(BaseModel):
    id: int
    name: str
    depot: str


class TeamMemberOut(BaseModel):
    employee_code: str
    display_name: str
    xp_total: int
    runs: int
    incidents: int
    weak: list[str]
    gaps: list[str]
    last_run_at: str | None


class TeamCompetencyOut(BaseModel):
    code: str
    title: str
    mean_mastery: float | None
    weak_count: int
    gap_count: int


class TeamAnalyticsResponse(BaseModel):
    brigade: BrigadeOut
    members: list[TeamMemberOut]
    competencies: list[TeamCompetencyOut]
    brigade_gaps: list[str]
    recommendations: list[RecommendationOut]
    summary: str


class ChallengeProgressOut(BaseModel):
    done: int
    total: int
    completed: bool


class ChallengeOut(BaseModel):
    id: str
    title: str
    description: str
    scenario_ids: list[str]
    bonus_points: int
    starts_at: str
    ends_at: str
    progress: ChallengeProgressOut
    bonus_expires_at: str | None
    status: str
