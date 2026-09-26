"""Сид: детерминизм двух прогонов, идемпотентность, отсутствие персональных данных в людях и
контенте, демо-профили под сценарий демонстрации и сама демонстрация: прохождение слабого
демо-проводника даёт достижение, новый уровень, рост XP, место в бригаде и прогресс челленджа."""

import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import clock
from app.config import load_settings
from app.db import make_engine, prepare_database
from app.main import create_app
from app.models import AchievementEarned, BonusPoint, Challenge, Employee, Notification, ScenarioRun
from app.scenarios.store import ContentStore
from app.seed import DEMO_ACCOUNTS, seed
from tests.test_analytics import SMOKING_BEST, play_scenario

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED_MOMENT = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
CYRILLIC_WORD = re.compile(r"^[А-ЯЁ][а-яё]+$")
PII_PATTERNS = {
    "телефон": re.compile(r"(?<!\d)(\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.IGNORECASE),
    "паспорт": re.compile(r"(?<!\d)\d{4}\s?\d{6}(?!\d)"),
    "СНИЛС": re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[ -]\d{2}(?!\d)"),
    "дата рождения": re.compile(r"(?<!\d)\d{2}\.\d{2}\.(19|20)\d{2}(?!\d)"),
}
PII_WORDS = re.compile(
    r"паспорт|снилс|дата рождения|день рождения|номер телефона|адрес проживания", re.IGNORECASE
)


def settings_for(path):
    os.environ["DATABASE_URL"] = "sqlite:///" + path.as_posix()
    os.environ["APP_ENV"] = "test"
    os.environ["FRONTEND_DIST"] = (path.parent / "dist").as_posix()
    return load_settings()


def seed_into(path, now=SEED_MOMENT):
    settings = settings_for(path)
    engine = make_engine(settings.database_url)
    prepare_database(engine)
    with sessionmaker(engine)() as db:
        created = seed(db, ContentStore(settings.content_dir), settings, now)
    engine.dispose()
    return created


def dump(path):
    """Канонический снимок таблиц без автоинкрементных id: по нему сравниваются два прогона."""
    engine = make_engine("sqlite:///" + path.as_posix())
    with sessionmaker(engine)() as db:
        codes = dict(db.execute(select(Employee.id, Employee.code)).all())
        people = sorted(
            (
                row.code,
                row.display_name,
                row.role,
                row.brigade.name,
                row.pin_salt,
                row.pin_hash,
                row.is_synthetic,
            )
            for row in db.scalars(select(Employee))
        )
        runs = sorted(
            (
                codes[row.employee_id],
                row.scenario_id,
                row.service_class,
                row.status,
                row.outcome,
                row.score,
                row.xp_earned,
                row.started_at,
            )
            for row in db.scalars(select(ScenarioRun))
        )
        bonuses = sorted(
            (codes[row.employee_id], row.points, row.reason, row.challenge_id, row.expires_at)
            for row in db.scalars(select(BonusPoint))
        )
        achievements = sorted(
            (codes[row.employee_id], row.achievement_id) for row in db.scalars(select(AchievementEarned))
        )
        notifications = sorted(
            (codes[row.employee_id], row.kind, row.title, row.read_at is None)
            for row in db.scalars(select(Notification))
        )
        challenges = sorted((row.id, row.starts_at, row.ends_at) for row in db.scalars(select(Challenge)))
    engine.dispose()
    return {
        "people": people,
        "runs": runs,
        "bonuses": bonuses,
        "achievements": achievements,
        "notifications": notifications,
        "challenges": challenges,
    }


@pytest.fixture(scope="module")
def history_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("history") / "template.db"
    assert seed_into(path) is True
    return path


@pytest.fixture
def history_client(tmp_path, history_template):
    target = tmp_path / "history.db"
    shutil.copy(history_template, target)
    # шаблон засеян в фиксированный момент: часы тестов встают через два часа после него,
    # чтобы окна челленджей и срок бонуса не зависели от времени запуска
    clock.freeze(SEED_MOMENT + timedelta(hours=2))
    with TestClient(create_app(settings_for(target))) as client:
        yield client


def login_as(client, code):
    response = client.post("/api/auth/login", json={"employee_code": code, "pin": "1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_seed_is_deterministic(history_template, tmp_path):
    again = tmp_path / "again.db"
    assert seed_into(again) is True
    first, second = dump(history_template), dump(again)
    assert first == second
    assert len(first["people"]) == 38 and len(first["runs"]) >= 100
    assert all(status == "finished" for _, _, _, status, *_ in first["runs"])


def test_seed_idempotent(history_template, tmp_path):
    before = dump(history_template)
    later = SEED_MOMENT.replace(hour=12)
    assert seed_into(history_template, now=later) is False
    assert dump(history_template) == before


def test_no_pii(history_template):
    snapshot = dump(history_template)
    texts = [name for _, name, *_ in snapshot["people"]]
    texts += [account["note"] for account in DEMO_ACCOUNTS]
    texts += [title for _, _, title, _ in snapshot["notifications"]]
    texts += [reason for _, _, reason, _, _ in snapshot["bonuses"]]
    texts += [path.read_text(encoding="utf-8") for path in CONTENT_DIR.rglob("*.yaml")]
    texts.append((BACKEND_DIR / "app" / "seed.py").read_text(encoding="utf-8"))
    for text in texts:
        for kind, pattern in PII_PATTERNS.items():
            assert not pattern.search(text), f"{kind}: {pattern.search(text).group(0)}"
        assert not PII_WORDS.search(text), PII_WORDS.search(text)
    for _, name, *_ in snapshot["people"]:
        words = name.split()
        assert len(words) == 3 and all(CYRILLIC_WORD.match(word) for word in words), name
        assert not name.startswith("Иванов"), name
    codes = [code for code, *_ in snapshot["people"]]
    assert len(set(codes)) == 38 and all(re.fullmatch(r"VSM-\d{4}", code) for code in codes)
    synthetic = all(person[-1] is True for person in snapshot["people"])
    assert synthetic, "в сиде есть сотрудник без метки синтетики"


def test_demo_accounts_profiles(history_client):
    client = history_client
    weak = login_as(client, "VSM-1001")
    profile = client.get("/api/profile", headers=weak).json()
    assert (
        0 < profile["xp_total"] < 150 and profile["level"]["id"] == "trainee" and profile["runs_count"] >= 1
    )
    assert len(profile["display_name"].split()) == 3
    runs = client.get("/api/profile/runs", headers=weak).json()
    assert all(run["scenario_id"] != "smoking_vestibule" for run in runs)
    assert all(run["status"] == "finished" for run in runs)
    medical = next(item for item in profile["competencies"] if item["code"] == "medical")
    assert (
        medical["mastery"] is not None
        and medical["mastery"] < 0.5
        and medical["status"] in ("few_data", "weak")
    )
    assert profile["bonus"]["active_total"] == 120
    assert [item["points"] for item in profile["bonus"]["expiring"]] == [30]
    listed = client.get("/api/notifications", headers=weak).json()
    expiring = [item for item in listed if item["kind"] == "points_expiring"]
    assert (
        len(expiring) == 1 and expiring[0]["title"] == "Сгорают 30 баллов" and expiring[0]["read_at"] is None
    )
    kinds = {item["kind"] for item in listed}
    assert "challenge" in kinds and "achievement" in kinds
    assert sum(item["read_at"] is None for item in listed) <= 8
    analytics = client.get("/api/analytics/me", headers=weak).json()
    assert any(item["competency"] == "medical" for item in analytics["recommendations"])
    strong = login_as(client, "VSM-1002")
    strong_profile = client.get("/api/profile", headers=strong).json()
    assert strong_profile["xp_total"] > profile["xp_total"] and strong_profile["achievements_count"] >= 3
    assert strong_profile["level"]["id"] in ("senior", "mentor", "expert")
    assert all(
        run["service_class"] == "first" for run in client.get("/api/profile/runs", headers=strong).json()
    )
    # старые уведомления из истории помечены прочитанными, последние остались непрочитанными
    strong_listed = client.get("/api/notifications", headers=strong).json()
    assert any(item["read_at"] for item in strong_listed) and any(
        item["read_at"] is None for item in strong_listed
    )
    assert len(client.get("/api/leaderboard?scope=brigade", headers=weak).json()["rows"]) == 6
    assert len(client.get("/api/leaderboard?scope=depot", headers=weak).json()["rows"]) == 18
    assert len(client.get("/api/leaderboard?scope=company&limit=100", headers=weak).json()["rows"]) == 36
    mentor = login_as(client, "VSM-2001")
    team = client.get("/api/analytics/team", headers=mentor).json()
    assert len(team["members"]) == 6 and team["brigade"]["name"] == "М-01"
    challenges = client.get("/api/challenges", headers=weak).json()
    assert [item["status"] for item in challenges] == ["active", "active", "active"]
    assert all(item["progress"]["done"] == 0 for item in challenges)
    demo = client.get("/api/auth/demo").json()
    assert [item["employee_code"] for item in demo] == ["VSM-1001", "VSM-1002", "VSM-2001"]
    assert demo[0]["display_name"] == profile["display_name"]


def test_demo_script(history_client):
    """Сценарий демонстрации: слабый демо-проводник образцово проходит «Дым в тамбуре»."""
    client = history_client
    headers = login_as(client, "VSM-1001")
    before = client.get("/api/profile", headers=headers).json()
    rank_before = client.get("/api/leaderboard?scope=brigade", headers=headers).json()["me"]["rank"]
    clock.freeze(clock.now())
    view = play_scenario(client, headers, "smoking_vestibule", SMOKING_BEST)
    assert view["outcome"] == "exemplary" and view["xp"] >= 150
    debrief = client.get(f"/api/runs/{view['run_id']}/debrief", headers=headers).json()
    breakdown = debrief["xp_breakdown"]
    assert debrief["is_repeat"] is False and view["xp"] == debrief["score"] == sum(breakdown.values())
    assert (breakdown["base"], breakdown["tempo"], breakdown["role"]) == (100, 5, 20)
    assert {"four_steps", "safety_first"} <= {item["id"] for item in debrief["achievements_new"]}
    assert (debrief["level_before"]["id"], debrief["level_after"]["id"]) == ("trainee", "conductor")
    after = client.get("/api/profile", headers=headers).json()
    assert after["xp_total"] == before["xp_total"] + view["xp"] and after["level"]["id"] == "conductor"
    assert after["rank_brigade"] < rank_before
    board = client.get("/api/leaderboard?scope=brigade", headers=headers).json()
    assert (
        board["me"]["rank"] == after["rank_brigade"] and board["me"]["best_scores_sum"] > before["xp_total"]
    )
    challenges = {item["id"]: item for item in client.get("/api/challenges", headers=headers).json()}
    assert challenges["safety_week"]["progress"] == {"done": 1, "total": 3, "completed": False}
    assert challenges["four_steps_week"]["progress"]["done"] == 1
    listed = client.get("/api/notifications", headers=headers).json()
    fresh = [item for item in listed if item["read_at"] is None]
    assert {"level_up", "achievement", "points_expiring", "challenge"} <= {item["kind"] for item in fresh}
