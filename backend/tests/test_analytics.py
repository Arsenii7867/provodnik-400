"""Аналитика компетенций: пробелы без прохождений, проседание после двух сценариев с
рекомендацией и причиной, своевременность эскалации в критических сценариях, темп, динамика по
неделям и отчёт по бригаде только для наставника."""

from app import clock
from tests.test_api_progress import play
from tests.test_api_sessions import error_code, play_best_path, start

ESCALATION_WEAK_MEDICAL = ["run_for_chief", "leave_to_meet_chief", "just_wait"]
ESCALATION_WEAK_SMOKING = ["harsh_demand", "threaten_police", "downplay_to_chief"]
SMOKING_BEST = ["acknowledge_ask_device", "rule_and_call_ptb", "offer_bistro_for_beer", "report_ecig_detail"]
# после истечения таймера вызов соседей с вердиктом bad считается лишней эскалацией
NEEDLESS_AFTER_EXPIRE = ["ask_neighbors_help", "ask_history_only", "pa_medic", "brief_medic", "announce_calm"]


def analytics_of(client, headers):
    response = client.get("/api/analytics/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def play_scenario(client, headers, scenario_id, moves, view=None):
    view = view or start(client, headers, scenario_id)
    for option_id in moves:
        response = client.post(
            f"/api/sessions/{view['run_id']}/choose",
            json={"option_id": option_id, "step_no": view["step_no"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        view = response.json()
    assert view["status"] == "finished", view["node"]
    return view


def test_gap_when_never_assessed(client, login):
    headers = login("VSM-1001")
    report = analytics_of(client, headers)
    assert report["runs_total"] == 0 and report["last_run_at"] is None
    assert all(item["status"] == "gap" and item["mastery"] is None for item in report["competencies"])
    assert report["gaps"] == [item["code"] for item in report["competencies"]] and report["weak"] == []
    assert report["summary"] == "Прохождений пока нет: начните с рекомендованных сценариев."
    starters = report["recommendations"]
    assert len(starters) == 3 and starters[0]["scenario_id"] == "smoking_vestibule"
    assert starters[0]["competency"] is None
    assert starters[0]["reason"].startswith("Прохождений пока нет: сложность 2")
    assert report["tempo"] == {
        "answered_avg_seconds": None,
        "timers_answered": 0,
        "timers_expired": 0,
        "on_time_share": None,
    }
    assert report["escalation"] == {"critical_runs": 0, "on_time": 0, "share": None, "needless": 0}
    assert len(report["weekly"]) == 8
    assert all(week["runs"] == 0 and week["avg_score"] is None for week in report["weekly"])
    assert report["mistakes"] == []
    # одно прохождение: инклюзивность так и не оценивалась, медицина оценена одним сценарием
    play_best_path(client, headers)
    report = analytics_of(client, headers)
    by_code = {item["code"]: item for item in report["competencies"]}
    assert by_code["inclusion"]["status"] == "gap" and "inclusion" in report["gaps"]
    assert by_code["medical"]["status"] == "few_data" and by_code["medical"]["mastery"] == 1.0
    assert report["weak"] == [] and report["runs_total"] == 1 and report["last_run_at"]


def test_competency_mastery_recommends(client, login):
    headers = login("VSM-1001")
    play_scenario(client, headers, "medical_chest_pain", ESCALATION_WEAK_MEDICAL)
    play_scenario(client, headers, "smoking_vestibule", ESCALATION_WEAK_SMOKING)
    report = analytics_of(client, headers)
    by_code = {item["code"]: item for item in report["competencies"]}
    assert by_code["escalation"]["status"] == "weak" and by_code["escalation"]["runs_assessed"] == 2
    assert by_code["escalation"]["mastery"] < 0.5
    assert "escalation" in report["weak"] and "inclusion" in report["gaps"]
    recommendations = report["recommendations"]
    assert 1 <= len(recommendations) <= 3
    assert len({item["scenario_id"] for item in recommendations}) == len(recommendations)
    weakest = min(report["weak"], key=lambda code: (by_code[code]["mastery"], code))
    assert recommendations[0]["competency"] == weakest
    for item in recommendations:
        title = by_code[item["competency"]]["title"]
        assert item["reason"].startswith(f"{title}: владение ") and "очк" in item["reason"]
        assert item["competency"] in report["weak"]
    assert report["summary"].startswith("Проседают «")
    assert report["summary"].endswith(f"Начните со сценария «{recommendations[0]['title']}».")
    mistakes = {item["competency"]: item for item in report["mistakes"]}
    assert mistakes["escalation"]["count"] >= 2
    assert mistakes["escalation"]["last_scenario_id"] == "smoking_vestibule"
    # образцово пройденный сценарий больше не рекомендуется
    play_best_path(client, headers)
    report = analytics_of(client, headers)
    assert "medical_chest_pain" not in {item["scenario_id"] for item in report["recommendations"]}


def test_escalation_timeliness(client, login):
    headers = login("VSM-1001")
    play_best_path(client, headers)
    report = analytics_of(client, headers)
    assert report["escalation"] == {"critical_runs": 1, "on_time": 1, "share": 1.0, "needless": 0}
    view = start(client, headers)
    clock.travel(21)
    body = {"step_no": view["step_no"]}
    view = client.post(f"/api/sessions/{view['run_id']}/expire", json=body, headers=headers).json()
    play_scenario(client, headers, "medical_chest_pain", NEEDLESS_AFTER_EXPIRE, view)
    report = analytics_of(client, headers)
    # вызов на втором шаге при ожидаемом первом уже поздний, а вызов соседей с вердиктом bad лишний
    assert report["escalation"] == {"critical_runs": 2, "on_time": 1, "share": 0.5, "needless": 1}
    assert report["tempo"]["timers_expired"] == 1 and report["tempo"]["timers_answered"] == 5
    assert report["tempo"]["on_time_share"] == 0.83
    play_scenario(client, headers, "smoking_vestibule", SMOKING_BEST)
    report = analytics_of(client, headers)
    assert report["escalation"]["critical_runs"] == 3 and report["escalation"]["on_time"] == 2
    assert "бригада вызвана вовремя в 2 из 3 прохождений" in report["summary"]


def test_weekly_dynamics(client, login):
    headers = login("VSM-1001")
    play_best_path(client, headers)
    clock.travel(14 * 24 * 3600)
    headers = login("VSM-1001")
    play(client, headers, ESCALATION_WEAK_MEDICAL)
    weekly = analytics_of(client, headers)["weekly"]
    assert len(weekly) == 8 and weekly[-1]["runs"] == 1 and weekly[-3]["runs"] == 1
    assert (weekly[-3]["avg_score"], weekly[-3]["incidents"], weekly[-3]["xp"]) == (185, 0, 185)
    assert weekly[-1]["xp"] < 185 and sum(week["runs"] for week in weekly) == 2
    starts = [week["week_start"] for week in weekly]
    assert starts == sorted(starts) and len(set(starts)) == 8
    assert all(clock.now().date().fromisoformat(start).weekday() == 0 for start in starts)


def test_team_analytics_mentor_only(client, login):
    conductor = login("VSM-1001")
    assert error_code(client.get("/api/analytics/team", headers=conductor), 403) == "role_required"
    play_scenario(client, conductor, "medical_chest_pain", ESCALATION_WEAK_MEDICAL)
    play_scenario(client, conductor, "smoking_vestibule", ESCALATION_WEAK_SMOKING)
    mentor = login("VSM-2001")
    team = client.get("/api/analytics/team", headers=mentor).json()
    assert team["brigade"]["name"] == "М-01" and team["brigade"]["depot"] == "ТЧ Москва-ВСМ"
    members = {item["employee_code"]: item for item in team["members"]}
    assert "VSM-2001" not in members and "VSM-1001" in members and "VSM-1002" in members
    first = members["VSM-1001"]
    assert first["runs"] == 2 and "escalation" in first["weak"] and "inclusion" in first["gaps"]
    assert first["xp_total"] > 0 and first["last_run_at"]
    assert members["VSM-1002"]["runs"] == 0 and len(members["VSM-1002"]["gaps"]) == 7
    by_code = {item["code"]: item for item in team["competencies"]}
    assert by_code["escalation"]["weak_count"] == 1 and by_code["escalation"]["mean_mastery"] < 0.5
    assert by_code["inclusion"]["mean_mastery"] is None
    assert by_code["inclusion"]["gap_count"] == len(team["members"])
    assert "inclusion" in team["brigade_gaps"] and "escalation" in team["brigade_gaps"]
    assert team["recommendations"] and team["recommendations"][0]["competency"] == "inclusion"
    assert team["recommendations"][0]["scenario_id"] == "wheelchair_boarding"
    assert team["summary"].startswith("В бригаде ") and "Бригаде стоит начать со сценария" in team["summary"]
    other_id = team["brigade"]["id"] + 1
    other = client.get(f"/api/analytics/team?brigade_id={other_id}", headers=mentor).json()
    assert other["brigade"]["name"] != "М-01" and other["summary"]
    missing = client.get("/api/analytics/team?brigade_id=999", headers=mentor)
    assert error_code(missing, 404) == "brigade_not_found"
