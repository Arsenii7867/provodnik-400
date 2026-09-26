"""Начальные данные: два депо, шесть бригад и демо-аккаунты с общим PIN из настроек.
Запуск `python -m app.seed` или автоматически при старте с AUTO_SEED=1 на пустой базе;
повторный запуск ничего не меняет. Люди синтетические: имена вымышленные, контактов нет."""

import sys

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import auth, clock
from app.config import load_settings
from app.db import make_engine, prepare_database
from app.models import Brigade, Depot, Employee, Profile

DEPOTS = {
    "ТЧ Москва-ВСМ": ("М-01", "М-02", "М-03"),
    "ТЧ Санкт-Петербург-ВСМ": ("С-01", "С-02", "С-03"),
}
DEMO_ACCOUNTS = (
    {
        "code": "VSM-1001",
        "display_name": "Артём Соколов",
        "role": "conductor",
        "brigade": "М-01",
        "note": "проводник стандарт-класса, бригада М-01",
    },
    {
        "code": "VSM-1002",
        "display_name": "Мария Лебедева",
        "role": "conductor",
        "brigade": "М-01",
        "note": "проводник первого класса, бригада М-01",
    },
    {
        "code": "VSM-2001",
        "display_name": "Игорь Крылов",
        "role": "mentor",
        "brigade": "М-01",
        "note": "наставник бригады М-01: аналитика команды и перезагрузка сценариев",
    },
)


def seed(db, settings, now) -> bool:
    """Заполняет пустую базу; при существующем депо ничего не делает и возвращает False."""
    if db.scalar(select(func.count()).select_from(Depot)):
        return False
    brigades = {}
    for depot_name, brigade_names in DEPOTS.items():
        depot = Depot(name=depot_name)
        db.add(depot)
        db.flush()
        for name in brigade_names:
            brigades[name] = Brigade(name=name, depot_id=depot.id)
            db.add(brigades[name])
    db.flush()
    for account in DEMO_ACCOUNTS:
        salt = auth.new_salt()
        employee = Employee(
            code=account["code"],
            display_name=account["display_name"],
            role=account["role"],
            brigade_id=brigades[account["brigade"]].id,
            pin_hash=auth.hash_pin(settings.demo_pin, salt),
            pin_salt=salt,
            is_synthetic=True,
            created_at=now,
        )
        db.add(employee)
        db.flush()
        db.add(Profile(employee_id=employee.id, xp_total=0, updated_at=now))
    db.commit()
    return True


def main():
    settings = load_settings()
    engine = make_engine(settings.database_url)
    prepare_database(engine)
    with sessionmaker(engine)() as db:
        created = seed(db, settings, clock.now())
    codes = ", ".join(account["code"] for account in DEMO_ACCOUNTS)
    print(f"База заполнена: демо-аккаунты {codes}" if created else "База уже заполнена, ничего не изменено")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
