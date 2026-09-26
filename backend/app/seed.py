"""Начальные данные: два депо, шесть бригад, 36 проводников и два наставника с вымышленными
именами из словарей (random.Random(20260926), поэтому два запуска дают одинаковых людей и
одинаковую историю), прохождения за последние шесть недель через тот же движок и сервис
прохождений, что и API (выборы и истечения таймеров по «умению» сотрудника), бонусы
демо-пользователю со сроком сгорания и окна челленджей. Запуск `python -m app.seed` или
автоматически при старте с AUTO_SEED=1 на пустой базе; повторный запуск ничего не меняет.
У людей нет ни телефонов, ни дат рождения, ни адресов: только код, имя, роль и бригада."""

import random
import sys
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import auth, clock
from app.config import load_settings
from app.db import make_engine, prepare_database
from app.models import BonusPoint, Brigade, Depot, Employee, Notification, Profile
from app.scenarios import engine
from app.scenarios.store import ContentStore
from app.services import challenges, session_service

SEED = 20260926
DEPOTS = {
    "ТЧ Москва-ВСМ": ("М-01", "М-02", "М-03"),
    "ТЧ Санкт-Петербург-ВСМ": ("С-01", "С-02", "С-03"),
}
CONDUCTORS_PER_BRIGADE = 6
MENTORS = {"VSM-2001": "М-01", "VSM-2002": "С-01"}
DEMO_ACCOUNTS = (
    {
        "code": "VSM-1001",
        "role": "conductor",
        "brigade": "М-01",
        "note": "проводник стандарт-класса, бригада М-01",
    },
    {
        "code": "VSM-1002",
        "role": "conductor",
        "brigade": "М-01",
        "note": "проводник первого класса, бригада М-01",
    },
    {
        "code": "VSM-2001",
        "role": "mentor",
        "brigade": "М-01",
        "note": "наставник бригады М-01: аналитика команды и перезагрузка сценариев",
    },
)
DEMO_WEAK = "VSM-1001"
DEMO_STRONG = "VSM-1002"
# сценарий демонстрации у слабого демо-проводника остаётся непройденным: первое прохождение даёт полный XP
DEMO_SCENARIO = "smoking_vestibule"
# слабый демо-проводник берёт вариант с минусом по этой компетенции, где такой показан; остальное как у всех
WEAK_COMPETENCY = "medical"
WEAK_OTHER_SKILL = 0.75
STRONG_SKILL = 0.9
STRONG_CLASS = "first"
SKILLS = (0.35, 0.55, 0.75, 0.9)
# соседи демо-проводника по бригаде расставлены лесенкой умения и числа прохождений, чтобы после
# демонстрации его место в бригаде менялось при любом наборе сценариев: двое слабее него, один с
# двумя безупречными прохождениями и один с четырьмя. Безупречные прохождения берутся из
# немедицинских сценариев: у них один таймер и потолок 175 очков, поэтому два таких прохождения
# дают от 322 до 350, а это больше 120 баллов бонусов демо-проводника с его провалами по медицине
# и меньше того же плюс образцовое демо-прохождение
DEMO_BRIGADE_LADDER = ((0.35, 1), (0.55, 2), (1.0, 2), (1.0, 4))
FLAWLESS_SKILL = 1.0
HISTORY_DAYS = 42
RUNS_MIN, RUNS_MAX = 2, 5
EXPIRE_FACTOR = 0.3
THINK_SECONDS = (3, 40)
UNREAD_KEEP = 3
# бонусы демо-проводника: часов до сгорания, баллы, причина
BONUS_LADDER = (
    (36, 30, "Челлендж «Четыре шага», прошлое окно"),
    (6 * 24, 50, "Челлендж «Неделя безопасности», прошлое окно"),
    (12 * 24, 40, "Челлендж «Инклюзия», прошлое окно"),
)

# fmt: off
MALE_NAMES = (
    "Александр", "Алексей", "Анатолий", "Андрей", "Антон", "Аркадий", "Арсений", "Артём",
    "Богдан", "Борис", "Вадим", "Валентин", "Валерий", "Василий", "Виктор", "Виталий",
    "Владимир", "Владислав", "Всеволод", "Вячеслав", "Геннадий", "Георгий", "Герман", "Глеб",
    "Григорий", "Даниил", "Денис", "Дмитрий", "Евгений", "Егор", "Ефим", "Игорь",
    "Илья", "Кирилл", "Константин", "Леонид", "Максим", "Марк", "Матвей", "Михаил",
)
FEMALE_NAMES = (
    "Александра", "Алина", "Алла", "Анастасия", "Ангелина", "Анна", "Антонина", "Валентина",
    "Валерия", "Варвара", "Вера", "Вероника", "Виктория", "Галина", "Дарья", "Диана",
    "Евгения", "Екатерина", "Елена", "Елизавета", "Жанна", "Зоя", "Инна", "Ирина",
    "Карина", "Кира", "Кристина", "Ксения", "Лариса", "Лидия", "Любовь", "Людмила",
    "Маргарита", "Марина", "Мария", "Надежда", "Наталья", "Нина", "Оксана", "Ольга",
)
PATRONYMICS = (
    "Александрович", "Алексеевич", "Анатольевич", "Андреевич", "Антонович", "Аркадьевич",
    "Артёмович", "Борисович", "Вадимович", "Валентинович", "Валерьевич", "Васильевич",
    "Викторович", "Витальевич", "Владимирович", "Владиславович", "Вячеславович", "Геннадьевич",
    "Георгиевич", "Германович", "Глебович", "Григорьевич", "Данилович", "Денисович",
    "Дмитриевич", "Евгеньевич", "Егорович", "Ефимович", "Игоревич", "Кириллович",
    "Константинович", "Леонидович", "Максимович", "Маркович", "Матвеевич", "Михайлович",
    "Николаевич", "Олегович", "Павлович", "Романович",
)
SURNAMES = (
    "Абрамов", "Авдеев", "Агафонов", "Аксёнов", "Алёхин", "Андрианов", "Анисимов", "Афанасьев",
    "Балашов", "Баранов", "Беляев", "Бирюков", "Блинов", "Богданов", "Бочаров", "Булатов",
    "Быков", "Васнецов", "Вешняков", "Виноградов", "Власов", "Волошин", "Воронин", "Гаврилов",
    "Галкин", "Герасимов", "Голубев", "Горбунов", "Гришин", "Гущин", "Давыдов", "Данилов",
    "Дементьев", "Денисов", "Дорофеев", "Дьяконов", "Евсеев", "Ежов", "Ермаков", "Ефимов",
    "Жданов", "Журавлёв", "Зайцев", "Захаров", "Зимин", "Золотарёв", "Зуев", "Игнатов",
    "Исаев", "Казаков", "Калинин", "Капустин", "Карпов", "Киселёв", "Ковалёв", "Кожевников",
    "Колесов", "Комаров", "Кондратьев", "Королёв", "Крылов", "Кудрявцев", "Кузнецов", "Лазарев",
    "Лапин", "Ларионов", "Лебедев", "Литвинов", "Логинов", "Лукин", "Макаров", "Мельников",
    "Миронов", "Мишин", "Моисеев", "Морозов", "Наумов", "Нестеров", "Никитин", "Носов",
)
# fmt: on


def female_patronymic(male):
    # Александрович даёт Александровну, Алексеевич даёт Алексеевну: меняется только окончание
    return male[:-2] + "на"


def full_name(rng):
    female = rng.random() < 0.5
    surname = rng.choice(SURNAMES)
    patronymic = rng.choice(PATRONYMICS)
    if female:
        # все фамилии словаря оканчиваются на -ов, -ев, -ёв или -ин: женская форма прибавляет «а»
        return f"{surname}а {rng.choice(FEMALE_NAMES)} {female_patronymic(patronymic)}"
    return f"{surname} {rng.choice(MALE_NAMES)} {patronymic}"


def create_people(db, rng, settings, now):
    """Депо, бригады, проводники VSM-1001.. по шесть на бригаду и наставники; PIN общий из
    настроек, соль из генератора, чтобы два прогона давали одинаковые хэши."""
    brigades = {}
    for depot_name, brigade_names in DEPOTS.items():
        depot = Depot(name=depot_name)
        db.add(depot)
        db.flush()
        for name in brigade_names:
            brigades[name] = Brigade(name=name, depot_id=depot.id)
            db.add(brigades[name])
    db.flush()
    employees = []
    number = 1001
    for name in brigades:
        for _ in range(CONDUCTORS_PER_BRIGADE):
            employees.append(
                add_employee(db, rng, settings, now, f"VSM-{number}", "conductor", brigades[name])
            )
            number += 1
    for code, name in MENTORS.items():
        employees.append(add_employee(db, rng, settings, now, code, "mentor", brigades[name]))
    db.flush()
    return employees


def add_employee(db, rng, settings, now, code, role, brigade):
    salt = rng.randbytes(16).hex()
    employee = Employee(
        code=code,
        display_name=full_name(rng),
        role=role,
        brigade_id=brigade.id,
        pin_hash=auth.hash_pin(settings.demo_pin, salt),
        pin_salt=salt,
        is_synthetic=True,
        created_at=now,
    )
    db.add(employee)
    db.flush()
    db.add(Profile(employee_id=employee.id, xp_total=0, updated_at=now))
    return employee


def plan_history(rng, employees, content):
    """Кому какие сценарии и с каким умением проходить: слабый демо-проводник проваливает
    сценарии с медициной и не трогает сценарий демонстрации, сильный проходит всё в первом
    классе, соседи по демо-бригаде идут лесенкой, остальные случайно."""
    scenario_ids = sorted(content.scenarios)
    ladder = iter(DEMO_BRIGADE_LADDER)
    plans = []
    for employee in employees:
        if employee.role != "conductor":
            continue
        if employee.code == DEMO_WEAK:
            medical = [sid for sid in scenario_ids if is_medical(content, sid) and sid != DEMO_SCENARIO]
            picks = [(sid, WEAK_OTHER_SKILL, None, WEAK_COMPETENCY) for sid in medical]
        elif employee.code == DEMO_STRONG:
            picks = [(sid, STRONG_SKILL, STRONG_CLASS, None) for sid in scenario_ids]
        elif employee.brigade.name == DEMO_ACCOUNTS[0]["brigade"]:
            skill, count = next(ladder)
            pool = scenario_ids
            if skill >= FLAWLESS_SKILL:
                pool = [sid for sid in scenario_ids if not is_medical(content, sid)]
            chosen = rng.sample(pool, min(count, len(pool)))
            picks = [(sid, skill, None, None) for sid in chosen]
        else:
            skill = rng.choice(SKILLS)
            count = rng.randint(RUNS_MIN, min(RUNS_MAX, len(scenario_ids)))
            picks = [(sid, skill, None, None) for sid in rng.sample(scenario_ids, count)]
            if rng.random() < 0.5:
                picks.append(picks[0])
        for pick in picks:
            plans.append((rng.uniform(1, HISTORY_DAYS), employee.code, *pick))
    # от старых к новым, чтобы порядок id прохождений совпадал с порядком во времени
    plans.sort(key=lambda plan: (-plan[0], plan[1], plan[2]))
    return plans


def is_medical(content, scenario_id):
    return WEAK_COMPETENCY in content.scenarios[scenario_id]["competencies"]


def pick_option(rng, options, skill, weak_in=None):
    """С вероятностью skill лучший вариант, иначе плохой; при отсутствии таких берётся любой.
    Слабый по компетенции сотрудник берёт вариант с минусом по ней, когда такой показан."""
    if weak_in:
        harmful = [option for option in options if (option.get("competencies") or {}).get(weak_in, 0) < 0]
        if harmful:
            return rng.choice(harmful)["id"]
    by_verdict = {}
    for option in options:
        by_verdict.setdefault(option["debrief"]["verdict"], []).append(option)
    wanted = ("best", "ok", "bad") if rng.random() < skill else ("bad", "ok", "best")
    pool = next(by_verdict[verdict] for verdict in wanted if verdict in by_verdict)
    return rng.choice(pool)["id"]


def play_run(db, store, employee, scenario_id, skill, service_class, weak_in, started_at, rng, grace):
    """Одно прохождение через сервис прохождений: те же дедлайны, шаги, итог и достижения,
    что у живого API; время течёт от started_at на секунды раздумий или до истечения таймера."""
    run, _ = session_service.start_run(db, store, employee, scenario_id, service_class, None, started_at)
    now = started_at
    while run.status == "active":
        scenario = store.scenario(scenario_id)
        state = session_service.deserialize_state(run.state_json)
        node = scenario["nodes"][state["node"]]
        seconds = engine.timer_seconds(node, state["service_class"])
        if seconds and rng.random() < EXPIRE_FACTOR * (1 - skill):
            now += timedelta(seconds=seconds + 2)
            session_service.expire(db, store, run, run.step_no, now, grace)
            continue
        if node["type"] == "event":
            option_id = engine.CONTINUE
        else:
            option_id = pick_option(rng, engine.available_options(scenario, state), skill, weak_in)
        longest = min(THINK_SECONDS[1], seconds - 2) if seconds else THINK_SECONDS[1]
        now += timedelta(seconds=rng.uniform(THINK_SECONDS[0], max(THINK_SECONDS[0] + 1, longest)))
        session_service.choose(db, store, run, option_id, run.step_no, now, grace)
    return run


def add_history(db, store, rng, employees, settings, now):
    content = store.content()
    by_code = {employee.code: employee for employee in employees}
    plans = plan_history(rng, employees, content)
    for days_ago, code, scenario_id, skill, service_class, weak_in in plans:
        started_at = now - timedelta(days=days_ago)
        grace = settings.timer_grace_seconds
        play_run(db, store, by_code[code], scenario_id, skill, service_class, weak_in, started_at, rng, grace)
    return len(plans)


def add_demo_bonuses(db, employees, now):
    demo = next(employee for employee in employees if employee.code == DEMO_WEAK)
    for hours, points, reason in BONUS_LADDER:
        db.add(
            BonusPoint(
                employee_id=demo.id,
                points=points,
                reason=reason,
                challenge_id=None,
                run_id=None,
                earned_at=now - timedelta(days=1),
                expires_at=now + timedelta(hours=hours),
            )
        )


def mark_history_read(db, employees, now):
    """Уведомления из истории помечаются прочитанными, кроме нескольких последних у каждого."""
    for employee in employees:
        rows = db.scalars(
            select(Notification)
            .where(Notification.employee_id == employee.id, Notification.created_at < now)
            .order_by(Notification.id.desc())
        ).all()
        for row in rows[UNREAD_KEEP:]:
            row.read_at = row.created_at


def seed(db, store, settings, now, history=True) -> bool:
    """Заполняет пустую базу; при существующем депо ничего не делает и возвращает False.
    history=False оставляет только людей и челленджи (так устроены тесты)."""
    if db.scalar(select(func.count()).select_from(Depot)):
        return False
    rng = random.Random(SEED)
    employees = create_people(db, rng, settings, now)
    db.commit()
    if history:
        add_history(db, store, rng, employees, settings, now)
        add_demo_bonuses(db, employees, now)
        mark_history_read(db, employees, now)
    challenges.activate(db, store.content(), now)
    db.commit()
    return True


def main():
    settings = load_settings()
    engine_ = make_engine(settings.database_url)
    prepare_database(engine_)
    with sessionmaker(engine_)() as db:
        created = seed(db, ContentStore(settings.content_dir), settings, clock.now())
        people = db.scalar(select(func.count()).select_from(Employee))
    codes = ", ".join(account["code"] for account in DEMO_ACCOUNTS)
    if created:
        print(f"База заполнена: сотрудников {people}, демо-аккаунты {codes}, PIN из DEMO_PIN")
    else:
        print("База уже заполнена, ничего не изменено")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
