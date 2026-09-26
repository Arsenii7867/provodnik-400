"""Аналитика бригады для наставника: по каждому проводнику владение, прохождения, инциденты,
проседающие и пробелы; по каждой компетенции среднее владение и счётчики; пробелы бригады,
рекомендации сценариев по худшим компетенциям и вывод фразой. Считается из тех же функций, что
личная аналитика, ничего не хранится."""

from sqlalchemy import select

from app import clock
from app.models import Employee, Profile
from app.services.analytics import finished_runs, mastery_for, points_word, potential
from app.services.texts import join_titles, plural


def member_view(db, content, member):
    runs = finished_runs(db, member.id)
    mastery = mastery_for(db, content, member.id)
    return {
        "employee_code": member.code,
        "display_name": member.display_name,
        "xp_total": db.scalar(select(Profile.xp_total).where(Profile.employee_id == member.id)) or 0,
        "runs": len(runs),
        "incidents": sum(run.outcome == "incident" for run in runs),
        "weak": [item["code"] for item in mastery if item["status"] == "weak"],
        "gaps": [item["code"] for item in mastery if item["status"] == "gap"],
        "last_run_at": clock.iso(runs[0].finished_at) if runs else None,
        "mastery": mastery,
    }


def team_competencies(content, members):
    rows = []
    for item in content.competencies:
        code = item["code"]
        values = [
            entry["mastery"] for member in members for entry in member["mastery"] if entry["code"] == code
        ]
        known = [value for value in values if value is not None]
        rows.append(
            {
                "code": code,
                "title": item["title"],
                "mean_mastery": round(sum(known) / len(known), 2) if known else None,
                "weak_count": sum(code in member["weak"] for member in members),
                "gap_count": sum(code in member["gaps"] for member in members),
            }
        )
    return rows


def team_recommendations(store, content, competencies, size, limit):
    """Сценарии для бригады по худшим компетенциям: пробелы у половины и больше сначала, потом
    низкое среднее; сценарий с наибольшим потенциалом по компетенции."""
    worst = sorted(
        competencies,
        key=lambda row: (
            row["mean_mastery"] if row["mean_mastery"] is not None else -1.0,
            -row["gap_count"],
            row["code"],
        ),
    )
    result = []
    used = set()
    for row in worst:
        scored = [
            (potential(store, key, row["code"]), key) for key in sorted(content.scenarios) if key not in used
        ]
        scored = sorted(
            ((points, key) for points, key in scored if points > 0), key=lambda pair: (-pair[0], pair[1])
        )
        if not scored:
            continue
        points, key = scored[0]
        used.add(key)
        if row["mean_mastery"] is None:
            state = f"не оценивалась у {row['gap_count']} из {size}"
        else:
            state = f"среднее владение {row['mean_mastery']:.2f}, проседает у {row['weak_count']} из {size}"
        result.append(
            {
                "scenario_id": key,
                "title": content.scenarios[key]["title"],
                "competency": row["code"],
                "reason": f"{row['title']}: {state}; на лучшем пути сценарий даёт до {points_word(points)}",
            }
        )
        if len(result) == limit:
            break
    return result


def team_summary(members, competencies, brigade_gaps, recommendations):
    if not members:
        return "В бригаде нет проводников."
    runs = sum(member["runs"] for member in members)
    incidents = sum(member["incidents"] for member in members)
    opening = (
        f"В бригаде {plural(len(members), 'проводник', 'проводника', 'проводников')}, "
        f"{plural(runs, 'прохождение', 'прохождения', 'прохождений')}, "
        f"{plural(incidents, 'инцидент', 'инцидента', 'инцидентов')}"
    )
    titles = {row["code"]: row["title"] for row in competencies}
    if brigade_gaps:
        opening += f"; пробелы бригады: {join_titles(titles[code] for code in brigade_gaps)}"
    if not recommendations:
        return f"{opening}."
    return f"{opening}. Бригаде стоит начать со сценария «{recommendations[0]['title']}»."


def team(db, store, brigade, now):
    content = store.content()
    rules = content.rules
    query = select(Employee).where(Employee.brigade_id == brigade.id, Employee.role == "conductor")
    members = [member_view(db, content, member) for member in db.scalars(query.order_by(Employee.code))]
    competencies = team_competencies(content, members)
    size = len(members)
    brigade_gaps = [
        row["code"]
        for row in competencies
        if size
        and (
            (row["mean_mastery"] is not None and row["mean_mastery"] < rules["mastery"]["weak_below"])
            or row["gap_count"] * 2 >= size
        )
    ]
    recommendations = team_recommendations(
        store, content, competencies, size, rules["analytics"]["recommendations"]
    )
    return {
        "brigade": {"id": brigade.id, "name": brigade.name, "depot": brigade.depot.name},
        "members": [{key: value for key, value in member.items() if key != "mastery"} for member in members],
        "competencies": competencies,
        "brigade_gaps": brigade_gaps,
        "recommendations": recommendations,
        "summary": team_summary(members, competencies, brigade_gaps, recommendations),
    }
