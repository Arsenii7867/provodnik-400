"""Подключение к базе: движок из DATABASE_URL, фабрика сессий и зависимость get_db.
SQLite получает WAL и busy_timeout, чтобы запросы фронта и тестов не ловили «database is
locked»; PostgreSQL по DATABASE_URL идёт через тот же код без отдельных веток."""

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi import Path as PathParam
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import Base

SQLITE_BUSY_TIMEOUT_MS = 5000
# id в SQLite и PostgreSQL 64-битные: число больше даёт OverflowError драйвера, а должно давать 422
MAX_ID = 2**63 - 1


def make_engine(database_url: str):
    if make_url(database_url).get_backend_name() != "sqlite":
        return create_engine(database_url)
    # соединение SQLite переходит между потоками пула uvicorn, поэтому проверка потока отключена
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", set_sqlite_pragmas)
    return engine


def set_sqlite_pragmas(connection, record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def prepare_database(engine):
    """Папка для файла SQLite и таблицы создаются при старте приложения, а не при импорте модуля."""
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_db(request: Request):
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


Db = Annotated[Session, Depends(get_db)]
EntityId = Annotated[int, PathParam(ge=1, le=MAX_ID)]
